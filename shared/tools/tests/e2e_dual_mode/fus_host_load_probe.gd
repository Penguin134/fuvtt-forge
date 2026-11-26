extends "res://tests/lib/ui_test_suite.gd"

## Real FUS Host-Load Probe executed inside cached `.cache/fus_host_mirror/<short_sha>/`.
## Tests built `.zip` (`fus.desktop-module.v1`), `.fup` (`fus.plugin.v2`), and v1 `.zip`
## packages against genuine FUS `SessionPlugins`, `DesktopFeatureCatalog`,
## `NetworkModuleContract`, `DesktopScreen`, `EditModeController`, and `WorldModuleState`.

const PluginService := preload("res://services/plugins/session_plugins.gd")
const ModuleContract := preload("res://scenes/board/networking/network_module_contract.gd")
const ModuleChoices := preload("res://scenes/extension/module_configuration.gd")

var _mode: String = "desktop"
var _zip_pkg: String = ""
var _fup_pkg: String = ""
var _v1_pkg: String = ""
var _comp_path: String = ""
var _details: Dictionary = {}


func _before_run() -> void:
	for arg: String in OS.get_cmdline_user_args():
		if arg.begins_with("--mode="):
			_mode = arg.trim_prefix("--mode=")
		elif arg.begins_with("--zip-pkg="):
			_zip_pkg = arg.trim_prefix("--zip-pkg=")
		elif arg.begins_with("--fup-pkg="):
			_fup_pkg = arg.trim_prefix("--fup-pkg=")
		elif arg.begins_with("--v1-pkg="):
			_v1_pkg = arg.trim_prefix("--v1-pkg=")
		elif arg.begins_with("--comp-path="):
			_comp_path = arg.trim_prefix("--comp-path=")


func _serve_and_install(plugins: Node, pkg_paths: Array[String]) -> void:
	var tcp := TCPServer.new()
	var listen_err: Error = tcp.listen(0, "127.0.0.1")
	_expect(listen_err == OK, "Local HTTP test server binds ephemeral port on 127.0.0.1")
	if listen_err != OK:
		return
	var port: int = tcp.get_local_port()

	for path: String in pkg_paths:
		if path.is_empty() or not FileAccess.file_exists(path):
			_expect(false, "Missing package path for HTTP install: " + path)
			continue
		var fname := path.get_file()
		var body: PackedByteArray = FileAccess.get_file_as_bytes(path)
		var url := "http://127.0.0.1:%d/%s" % [port, fname]
		var started: bool = plugins.request("install", {"url": url})
		_expect(started, "SessionPlugins starts HTTP install for " + fname)
		var deadline_ms: int = Time.get_ticks_msec() + 15000
		var active_peers: Array[StreamPeerTCP] = []
		while plugins.busy and Time.get_ticks_msec() < deadline_ms:
			while tcp.is_connection_available():
				var peer := tcp.take_connection()
				if peer != null:
					active_peers.append(peer)
			for i: int in range(active_peers.size() - 1, -1, -1):
				var p := active_peers[i]
				p.poll()
				if p.get_status() == StreamPeerTCP.STATUS_CONNECTED and p.get_available_bytes() > 0:
					var _req := p.get_utf8_string(p.get_available_bytes())
					var hdr := "HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % body.size()
					p.put_data(hdr.to_utf8_buffer() + body)
					p.disconnect_from_host()
					active_peers.remove_at(i)
			await process_frame
		_expect(bool(plugins.last_result.get("ok", false)),
			"PluginPackageJob installs %s cleanly (reason=%s)" % [fname, String(plugins.last_result.get("reason", ""))])
	tcp.stop()


func _run() -> void:
	var plugin_profile := OUT.trim_suffix("/").path_join("plugin_profile")
	DirAccess.make_dir_recursive_absolute(plugin_profile)
	var plugins: Node = PluginService.new()
	root.add_child(plugins)
	plugins.bind_storage(plugin_profile)

	var pkgs: Array[String] = []
	if not _v1_pkg.is_empty():
		pkgs.append(_v1_pkg)
	if not _zip_pkg.is_empty():
		pkgs.append(_zip_pkg)
	if not _fup_pkg.is_empty():
		pkgs.append(_fup_pkg)

	await _serve_and_install(plugins, pkgs)
	_details["installed_rows"] = plugins.rows.size()

	var cat_ids: Array[String] = []
	for entry: Dictionary in DesktopFeatureCatalog.optional_entries():
		cat_ids.append(String(entry.get("id", "")))
	_details["catalog_ids"] = cat_ids

	if _mode == "coexist":
		_expect(plugins.rows.size() >= 3, "Tri-schema coexistence installs >= 3 plugins into SessionPlugins")
		plugins.queue_free()
		await _settle()
		_write_report()
		_finish()
		return

	root.size = Vector2i(1280, 720)
	var desk_profile := OUT.trim_suffix("/").path_join("desktop_profile/profile.cfg")
	DirAccess.make_dir_recursive_absolute(desk_profile.get_base_dir())
	var desktop_scene := load("res://scenes/desktop/desktop_screen.tscn") as PackedScene
	var desktop: Node = desktop_scene.instantiate()
	desktop.configure({"player_name": "E2E Host", "session_path": ""}, desk_profile)
	root.add_child(desktop)
	current_scene = desktop
	await _settle()

	var runtime: Node = desktop.get_extension_runtime()
	var manager: Node = runtime.get_node("FeatureManager")
	var slots: SlotRegistry = runtime.get_node("SlotRegistry") as SlotRegistry
	var persistence: Node = desktop.get_node("%Persistence")
	var editor: EditModeController = desktop.get_node("%EditModeController") as EditModeController
	var store: Node = desktop.get_node("%Entities")
	(persistence.get_node("AutosaveTimer") as Timer).stop()
	if persistence.has_node("ModuleAutosaveTimer"):
		(persistence.get_node("ModuleAutosaveTimer") as Timer).stop()

	var target_mod_ids: Array[Dictionary] = []
	for cid: String in cat_ids:
		if not cid.is_empty() and cid not in ["scene_box", "dice", "stat_bubbles"]:
			for row: Dictionary in plugins.rows:
				var manifest: Dictionary = row.get("manifest", {}) as Dictionary
				var mods_arr: Array = manifest.get("modules", []) as Array
				if mods_arr.is_empty() and manifest.get("module") is Dictionary:
					mods_arr = [manifest.get("module")]
				for m: Variant in mods_arr:
					if m is Dictionary and String((m as Dictionary).get("id", "")) == cid:
						target_mod_ids.append({"id": cid, "enabled": true})

	_expect(not target_mod_ids.is_empty(), "External module entries discovered in DesktopFeatureCatalog")
	if not target_mod_ids.is_empty():
		_expect(ModuleContract.campaign_supported(target_mod_ids, {}),
			"NetworkModuleContract.campaign_supported passes for enabled external modules")
		var enable_choices := target_mod_ids.duplicate()
		if _mode == "world":
			enable_choices.append({"id": "scene_box", "enabled": true})
		var en_res: Dictionary = await persistence.request_module_choices(enable_choices)
		_expect(bool(en_res.get("ok", false)), "Desktop enables external modules cleanly")
		await _settle()

		var slot_items_while_enabled := 0
		for entry_cfg: Dictionary in target_mod_ids:
			slot_items_while_enabled += slots.items_by_source(String(entry_cfg["id"])).size()
		_details["slot_items_while_enabled"] = slot_items_while_enabled
		_expect(slot_items_while_enabled >= 1,
			"DesktopScreen SlotRegistry has >= 1 registered item while external module is enabled")

		var desktop_api: Object = runtime.consume_service("desktop_api")
		_expect(desktop_api != null and bool(desktop_api.call(&"is_gm")), "desktop_api service active")

		if _mode == "desktop":
			var net_manifest: Array[Dictionary] = manager.network_module_manifest()
			for entry_cfg: Dictionary in target_mod_ids:
				var mid := String(entry_cfg["id"])
				var in_net := false
				for nm: Dictionary in net_manifest:
					if String(nm.get("id", "")) == mid:
						in_net = true
				_expect(not in_net, "local_only module %s excluded from network_module_manifest" % mid)
			_expect(bool(manager.network_configuration_ready()), "network_configuration_ready stays true with local_only mod")

		if _mode == "world" and is_instance_valid(store) and is_instance_valid(editor):
			var paladin: BoardToken = store.create_entity("Paladin", Vector2(256, 256)) as BoardToken
			await _settle()
			_expect(paladin != null, "Created Paladin BoardToken in DesktopScreen")
			if paladin != null and not _comp_path.is_empty():
				var attach_ok: bool = editor.components_request([paladin] as Array[BoardToken], _comp_path, &"activate")
				var comp_id: String = CompBase.id_from_path(_comp_path)
				var attached: CompBase = paladin.get_component_by_id(comp_id)
				_details["component_attached"] = attach_ok and attached != null
				_expect(attach_ok and attached != null, "Attached custom component %s on Paladin" % comp_id)

	# Clean disable all optional modules
	(persistence.get_node("AutosaveTimer") as Timer).stop()
	if persistence.has_node("ModuleAutosaveTimer"):
		(persistence.get_node("ModuleAutosaveTimer") as Timer).stop()
	await persistence.request_module_choices([])
	await _settle()
	for entry_cfg: Dictionary in target_mod_ids:
		var mid := String(entry_cfg["id"])
		_expect(slots.items_by_source(mid).is_empty(), "Zero residual slots left for disabled module " + mid)

	desktop.deactivate()
	desktop.queue_free()
	plugins.queue_free()
	await _settle()
	_write_report()
	_finish()


func _write_report() -> void:
	var report := {
		"ok": _failures.is_empty(),
		"checks": _checks,
		"failures": _failures,
		"details": _details,
	}
	var fa := FileAccess.open(OUT.path_join("host_probe_report.json"), FileAccess.WRITE)
	if fa != null:
		fa.store_string(JSON.stringify(report, "\t") + "\n")
		fa.close()
