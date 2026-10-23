extends SceneTree

func _initialize() -> void:
	call_deferred("_capture")

func _capture() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() < 1:
		quit(2)
		return
	var file := FileAccess.open(args[0], FileAccess.READ)
	if file == null:
		quit(2)
		return
	var config = JSON.parse_string(file.get_as_text())
	file.close()
	if not config is Dictionary:
		quit(2)
		return
	root.size = Vector2i(int(config.width), int(config.height))
	var adapter := RenderingServer.get_video_adapter_name().to_lower()
	for software in ["llvmpipe", "lavapipe", "swiftshader", "microsoft basic", "software"]:
		if adapter.contains(software):
			quit(6)
			return
	var result := change_scene_to_file("res://" + String(config.scene))
	if result != OK:
		quit(3)
		return
	var deadline := Time.get_ticks_msec() + int(float(config.wait_seconds) * 1000.0)
	while Time.get_ticks_msec() < deadline:
		await process_frame
	await RenderingServer.frame_post_draw
	var image := root.get_texture().get_image()
	if image == null or image.is_empty():
		quit(4)
		return
	var saved := image.save_png(String(config.output))
	quit(0 if saved == OK else 5)
