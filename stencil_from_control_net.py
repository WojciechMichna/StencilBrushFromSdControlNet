bl_info = {
    "name": "Stencil Brush from Depth ControlNet",
    "blender": (4, 0, 0),
    "category": "Object",
    "version": (0, 0, 1),
    "author": "Wojciech Michna",
    "description": "Create stencil brush using Depth ControlNet",
}

import bpy
import os
import urllib.request
import json
import mathutils
import gzip
from io import BytesIO
import base64


class SdProperties(bpy.types.PropertyGroup):
    sd_prompt: bpy.props.StringProperty(
        name="prompt", description="Stable diffusion prompt"
    )
    sd_negative_prompt: bpy.props.StringProperty(
        name="negative prompt", description="Stable diffusion negative prompt"
    )
    sd_api_ip: bpy.props.StringProperty(
        name="SD API IP",
        description="Stable diffusion API host",
        default="127.0.0.1",
    )
    sd_api_port: bpy.props.IntProperty(
        name="SD API PORT",
        description="Stable diffusion API port",
        default=7860,
    )
    image_width: bpy.props.IntProperty(
        name="Image width",
        description="Image width",
        default=512,
    )
    image_height: bpy.props.IntProperty(
        name="Image height",
        description="Image height",
        default=512,
    )
    denoising_strength: bpy.props.FloatProperty(
        name="Denoising strength",
        description="Denoising strength",
        default=0.7,
        min=0.0,
        max=1.0,
    )
    remove_tmp_files: bpy.props.BoolProperty(
        name="Remove tmp files", description="Remove temporary files", default=True
    )

    available_sd_models: bpy.props.StringProperty(name="available_sd_models")
    available_controlnet_models: bpy.props.StringProperty(
        name="available_controlnet_models"
    )

    def update_brush_texture_alpha(self, context):
        brush = context.tool_settings.image_paint.brush
        brush.texture_overlay_alpha = self.overlay_alpha
        bpy.context.area.tag_redraw()

    def sd_model_callback(self, context):
        items = []
        if len(self.available_sd_models) > 0:
            return [tuple(item) for item in json.loads(self.available_sd_models)]
        return items

    def controlnet_callback(self, context):
        items = []
        if len(self.available_controlnet_models) > 0:
            return [
                (item, item, "")
                for item in json.loads(self.available_controlnet_models)
            ]
        return items

    sd_model: bpy.props.EnumProperty(
        name="SD Models", description="Select an option", items=sd_model_callback
    )

    controlnet_model: bpy.props.EnumProperty(
        name="control Net Models",
        description="Select an option",
        items=controlnet_callback,
    )

    depth_preprocessor: bpy.props.EnumProperty(
        name="Depth Preprocessor",
        description="Select preprocessor used for depth control net",
        items=[
            ("depth_midas", "depth_midas", ""),
            ("depth_zoe", "depth_zoe", ""),
            ("depth_leres++", "depth_leres++", ""),
            ("depth_leres", "depth_leres", ""),
            ("depth_hand_refiner", "depth_hand_refiner", ""),
            ("depth_anything_v2", "depth_anything_v2", ""),
            ("depth_anything", "depth_anything", ""),
        ],
    )

    overlay_alpha: bpy.props.IntProperty(
        name="Overlay Alpha",
        description="Control the texture overlay opacity",
        default=33,
        min=0,
        max=100,
        update=update_brush_texture_alpha,
    )


class SendToControlNetOperator(bpy.types.Operator):
    bl_idname = "mesh.send_to_control_net"
    bl_label = "Send to Control Net"
    bl_description = "Send current view to Control Net"

    button_id: bpy.props.StringProperty()

    def crop_image_to_aspect_ratio(self, target_width, target_height, image_path):
        """
        Crop an image to the aspect ratio defined by target_width and target_height.

        :param target_width: Desired width for aspect ratio calculation.
        :param target_height: Desired height for aspect ratio calculation.
        :param image_path: Path to the image file to be cropped.
        """
        # Calculate the desired aspect ratio
        aspect_ratio = target_width / target_height

        # Load the image
        try:
            img = bpy.data.images.load(image_path)
        except:
            print(f"Unable to load image at {image_path}")
            return

        orig_width, orig_height = img.size
        img_aspect_ratio = orig_width / orig_height

        # Get the pixel data from the image
        pixels = list(img.pixels)

        if img_aspect_ratio > aspect_ratio:
            # Need to crop width
            new_width = int(aspect_ratio * orig_height)
            new_height = orig_height
            pixels_to_remove = orig_width - new_width
            left = int(pixels_to_remove / 2)

            # Create new image
            new_img = bpy.data.images.new(
                "Cropped Image", width=new_width, height=new_height
            )
            new_pixels = [0.0] * (new_width * new_height * 4)

            # Copy pixels
            for y in range(new_height):
                for x in range(new_width):
                    orig_x = x + left
                    orig_y = y
                    orig_index = (orig_y * orig_width + orig_x) * 4
                    new_index = (y * new_width + x) * 4
                    new_pixels[new_index : new_index + 4] = pixels[
                        orig_index : orig_index + 4
                    ]

        elif img_aspect_ratio < aspect_ratio:
            # Need to crop height
            new_height = int(orig_width / aspect_ratio)
            new_width = orig_width
            pixels_to_remove = orig_height - new_height
            top = int(pixels_to_remove / 2)
            new_img = bpy.data.images.new(
                "Cropped Image", width=new_width, height=new_height
            )
            new_pixels = [0.0] * (new_width * new_height * 4)

            # Copy pixels
            for y in range(new_height):
                orig_y = y + top
                for x in range(new_width):
                    orig_x = x
                    orig_index = (orig_y * orig_width + orig_x) * 4
                    new_index = (y * new_width + x) * 4
                    new_pixels[new_index : new_index + 4] = pixels[
                        orig_index : orig_index + 4
                    ]

        else:
            # Aspect ratio matches, no need to crop
            print("Aspect ratio matches, no cropping needed.")
            return

        # Assign pixels to new image
        new_img.pixels = new_pixels

        new_img.filepath_raw = img.filepath_raw
        new_img.file_format = (
            img.file_format
        )  # Use the same format as the original image
        bpy.data.images.remove(img)
        new_img.save()
        bpy.data.images.remove(new_img)

    def find_center_point(self, points):
        if not points:
            return None

        n = len(points)
        sum_x = sum(point[0] for point in points)
        sum_y = sum(point[1] for point in points)

        center_x = sum_x / n
        center_y = sum_y / n

        return int(center_x), int(center_y)

    def project_3d_to_2d(self, rv3d, coord):
        """
        Projects a 3D point to 2D screen space in the viewport.
        This version uses the correct combination of the projection matrix and view matrix.
        - region: The 3D Viewport region.
        - rv3d: The RegionView3D (viewport's region 3D).
        - coord: The 3D coordinate to project.
        """
        # World to view transformation (view_matrix)
        view_matrix = rv3d.view_matrix

        # View to projection transformation (perspective_matrix)
        projection_matrix = rv3d.window_matrix

        # Apply the full transformation (view * projection) on the 3D coordinate
        coord_4d = view_matrix @ mathutils.Vector((coord[0], coord[1], coord[2], 1.0))
        coord_ndc = projection_matrix @ coord_4d

        # If the point is behind the camera (w <= 0), it's not visible
        if coord_ndc.w <= 0.0:
            return None

        # Convert from homogeneous coordinates (clip space) to normalized device coordinates (NDC)
        coord_ndc /= coord_ndc.w

        # NDC coordinates range from -1 to 1, so we need to map them to screen space
        x = int((0.5 + coord_ndc.x / 2.0) * bpy.context.scene.render.resolution_x)
        y = int((0.5 + coord_ndc.y / 2.0) * bpy.context.scene.render.resolution_y)
        return x, y

    def annotate_to_points(self):
        # Step 2: Get the 3D Viewport region and RegionView3D for projection
        points_2d = []  # Store 2D points to draw red dots later

        for area in bpy.context.window.screen.areas:
            if area.type == "VIEW_3D":
                region = None
                for region_ in area.regions:
                    if region_.type == "WINDOW":
                        region = region_
                        break

                rv3d = area.spaces.active.region_3d

                # Step 3: Project 3D Grease Pencil points into 2D coordinates
                for gpencil in bpy.data.grease_pencils:
                    for layer in gpencil.layers:
                        for frame in layer.frames:
                            for stroke in frame.strokes:
                                for point in stroke.points:
                                    # Get the 3D coordinate of the point
                                    point_3d = point.co

                                    # Project the 3D point to 2D viewport coordinates
                                    point_2d = self.project_3d_to_2d(rv3d, point_3d)

                                    if point_2d is not None:
                                        points_2d.append(point_2d)
        return points_2d

    def create_brush(self, image_path, brush_tool):
        # Ensure the image file exists
        if not os.path.isfile(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")

        # Load the image
        image = bpy.data.images.load(image_path)

        # Create a new texture and assign the image to it
        texture = bpy.data.textures.new(name="BrushTexture", type="IMAGE")
        texture.image = image

        # Create a new brush for texture painting
        new_brush = bpy.data.brushes.new(name="StencilBrush", mode="TEXTURE_PAINT")

        # Assign the texture to the brush
        new_brush.texture = texture

        # Set the texture mapping to 'Stencil'
        new_brush.texture_slot.map_mode = "STENCIL"

        # Set the new brush as the active brush in Texture Paint mode
        bpy.context.tool_settings.image_paint.brush = new_brush

        v3d_list = [area for area in bpy.context.screen.areas if area.type == "VIEW_3D"]
        if v3d_list:
            main_v3d = max(v3d_list, key=lambda area: area.width * area.height)
            x = main_v3d.width / 2
            y = main_v3d.height / 2
            bpy.data.brushes[new_brush.name].stencil_pos.xy = x, y

        # Change the opacity in the viewport
        brush = bpy.context.tool_settings.image_paint.brush
        brush.texture_overlay_alpha = brush_tool.overlay_alpha
        bpy.context.area.tag_redraw()

        print("New stencil brush created and set as active.")

    def send_request_to_sd(self, brush_tool, image_path, mask_path=None):

        inpainting = False

        if "txt2img" in self.button_id:
            img2img = False
            url = f"http://{brush_tool.sd_api_ip}:{brush_tool.sd_api_port}/sdapi/v1/txt2img"
        elif "img2img" in self.button_id or "inpainting" in self.button_id:
            img2img = True
            inpainting = "inpainting" in self.button_id
            url = f"http://{brush_tool.sd_api_ip}:{brush_tool.sd_api_port}/sdapi/v1/img2img"

        if inpainting and mask_path is not None:
            self.crop_image_to_aspect_ratio(
                brush_tool.image_width, brush_tool.image_height, image_path
            )
            self.crop_image_to_aspect_ratio(
                brush_tool.image_width, brush_tool.image_height, mask_path
            )

        # Define the headers
        headers = {
            "Accept": "*/*",
            "Accept-Encoding": "deflate, gzip",
            "Content-Type": "application/json",
        }

        with open(image_path, "rb") as img_file:
            base64_image = base64.b64encode(img_file.read()).decode("utf-8")

        # Define the data payload
        data = {
            "init_images": [base64_image],
            "prompt": f"{brush_tool.sd_prompt}",
            "negative_prompt": f"{brush_tool.sd_negative_prompt}",
            "sampler_name": "DPM++ 2M",
            "batch_size": 1,
            "n_iter": 1,
            "steps": 20,
            "cfg_scale": 7.5,
            "width": brush_tool.image_width,
            "height": brush_tool.image_height,
            "seed": 1645176225,
            "refiner_checkpoint": "",
            "refiner_switch_at": 0.56,
            "tiling": False,
            "enable_hr": False,
            "hr_upscaler": "",
            "hr_sampler_name": "DPM++ 2M",
            "hr_scale": 1.0,
            "denoising_strength": brush_tool.denoising_strength,
            "hr_second_pass_steps": 15,
            "override_settings": {"sd_model_checkpoint": brush_tool.sd_model},
            "alwayson_scripts": {
                "controlnet": {
                    "args": [
                        {
                            "enabled": True,
                            "image": base64_image,
                            "resize_mode": "Crop and Resize",
                            "module": brush_tool.depth_preprocessor,
                            "model": brush_tool.controlnet_model,
                            "weight": 1.0,
                            "low_vram": False,
                            "processor_res": 512.0,
                            "threshold_a": 0.5,
                            "threshold_b": 0.5,
                            "guidance_start": 0.0,
                            "guidance_end": 1.0,
                            "control_mode": "Balanced",
                            "pixel_perfect": False,
                            "batch_image_dir": "",
                            "batch_mask_dir": "",
                            "hr_option": "Both",
                            "input_mode": "simple",
                            "save_detected_map": True,
                            "save_images": True,
                            "use_preview_as_input": False,
                        }
                    ]
                }
            },
        }

        if img2img or inpainting:
            data["init_images"] = [base64_image]

        if inpainting:
            with open(mask_path, "rb") as mask_file:
                base64_mask = base64.b64encode(mask_file.read()).decode("utf-8")
                data["mask"] = base64_mask
                data["inpainting_fill"] = 1
                data["inpaint_full_res"] = 0
                data["inpaint_full_res_padding"] = 0
                data["inpainting_mask_invert"] = 0
                data["mask_blur"] = 0
                data["alwayson_scripts"]["Soft Inpainting"] = {
                    "args": [
                        {
                            "Soft inpainting": True,
                            "Schedule bias": 1.0,
                            "Preservation strength": 0.5,
                            "Transition contrast boost": 4.0,
                            "Mask influence": 0.0,
                            "Difference threshold": 0.5,
                            "Difference contrast": 2.0,
                        }
                    ]
                }

        # Convert the data to JSON
        data_json = json.dumps(data).encode("utf-8")

        # Create the request
        req = urllib.request.Request(url, data=data_json, headers=headers)

        ret = []

        with urllib.request.urlopen(req, timeout=None) as response:
            # Check if the response is gzipped
            if response.getheader("Content-Encoding") == "gzip":
                # Read and decompress the response
                buf = BytesIO(response.read())
                decompressed_data = gzip.GzipFile(fileobj=buf).read()
            else:
                # If not gzipped, read the response directly
                decompressed_data = response.read()

            # Decode the decompressed data and print it
            response_text = decompressed_data.decode("utf-8")
            response_json = json.loads(response_text)

            for idx, img_data in enumerate(response_json["images"]):
                # Decode the base64 image data
                img_bytes = base64.b64decode(img_data)
                file_path = os.path.join(bpy.app.tempdir, f"sd_image_{idx + 1}.png")
                # Save the image to a PNG file
                with open(file_path, "wb") as img_file:
                    img_file.write(img_bytes)
                ret.append(file_path)

        return ret

    def get_sd_models(self, context):
        brush_tool = context.scene.control_net_brush_tool
        models_url = (
            f"http://{brush_tool.sd_api_ip}:{brush_tool.sd_api_port}/sdapi/v1/sd-models"
        )
        control_net_models = f"http://{brush_tool.sd_api_ip}:{brush_tool.sd_api_port}/controlnet/model_list"

        try:
            req = urllib.request.Request(models_url)
            with urllib.request.urlopen(req) as response:
                data = response.read()
                sd_models = json.loads(data)
                brush_tool.available_sd_models = json.dumps(
                    [
                        (models["title"], models["model_name"], "")
                        for models in sd_models
                    ]
                )
            req = urllib.request.Request(control_net_models)
            with urllib.request.urlopen(req) as response:
                data = response.read()
                control_net_models = json.loads(data)
                brush_tool.available_controlnet_models = json.dumps(
                    control_net_models["model_list"]
                )
        except urllib.error.URLError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        return {"FINISHED"}

    def get_viewport_capture(self):
        output_path = os.path.join(bpy.app.tempdir, "viewport_capture.png")

        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                for space in area.spaces:
                    if space.type == "VIEW_3D":
                        previous_overlays_state = space.overlay.show_overlays
                        previous_annotation_state = space.overlay.show_annotation
                        space.overlay.show_overlays = False
                        space.overlay.show_annotation = False
                        # Capture the viewport using OpenGL without saving to a file
                        bpy.ops.render.opengl(write_still=False, view_context=True)
                        space.overlay.show_overlays = previous_overlays_state
                        space.overlay.show_annotation = previous_annotation_state

        # Access the 'Render Result' image
        render_result = bpy.data.images.get("Render Result")
        # Check if the image exists
        if render_result:
            # Save the image manually to the specified path
            render_result.save_render(filepath=output_path)
            return output_path
        else:
            return None

    def create_mask_from_annotation(self, viewport_image_path):
        image = bpy.data.images.load(viewport_image_path)
        points_2d = self.annotate_to_points()
        if len(points_2d) == 0:
            return None

        width, height = image.size
        pixels = list(image.pixels[:])  # Copy the current pixels

        for i in range(0, len(pixels), 4):
            pixels[i] = 0.0  # R
            pixels[i + 1] = 0.0  # G
            pixels[i + 2] = 0.0  # B
            pixels[i + 3] = 1.0  # A

        # Function to set the pixel color at (x, y)
        def set_pixel_t(image_pixels, x, y, width, color):
            """Set a pixel's color in the image's pixel array"""
            index = (
                y * width + x
            ) * 4  # Calculate index in flat array (4 channels: R, G, B, A)
            image_pixels[index : index + 3] = color  # Set RGB
            image_pixels[index + 3] = 1.0  # Set alpha to 1 (fully opaque)

        # Function to draw a line between two points
        def draw_line(image_pixels, width, height, x0, y0, x1, y1, color):
            x0 = int(round(x0))
            y0 = int(round(y0))
            x1 = int(round(x1))
            y1 = int(round(y1))

            dx = abs(x1 - x0)
            dy = -abs(y1 - y0)
            sx = 1 if x0 < x1 else -1
            sy = 1 if y0 < y1 else -1
            err = dx + dy  # error value e_xy

            while True:
                if 0 <= x0 < width and 0 <= y0 < height:
                    set_pixel_t(image_pixels, x0, y0, width, color)
                if x0 == x1 and y0 == y1:
                    break
                e2 = 2 * err
                if e2 >= dy:
                    err += dy
                    x0 += sx
                if e2 <= dx:
                    err += dx
                    y0 += sy

        # Perform flood fill starting from center_point, filling with red color
        def flood_fill(image_pixels, x, y, width, height):
            x = int(round(x))
            y = int(round(y))

            if not (0 <= x < width and 0 <= y < height):
                return

            stack = [(x, y)]
            while stack:
                x, y = stack.pop()
                index = (y * width + x) * 4
                current_color = image_pixels[index : index + 3]
                if current_color == [0.0, 0.0, 0.0]:  # If the pixel is black
                    # Set pixel to red
                    image_pixels[index] = 1.0  # R
                    image_pixels[index + 1] = 1.0  # G
                    image_pixels[index + 2] = 1.0  # B
                    image_pixels[index + 3] = 1.0  # A
                    # Add neighboring pixels to the stack
                    if x > 0:
                        stack.append((x - 1, y))
                    if x < width - 1:
                        stack.append((x + 1, y))
                    if y > 0:
                        stack.append((x, y - 1))
                    if y < height - 1:
                        stack.append((x, y + 1))

        white = [1.0, 1.0, 1.0]
        num_points = len(points_2d)
        for i in range(num_points):
            x0, y0 = points_2d[i]
            x1, y1 = points_2d[(i + 1) % num_points]  # Wrap around to the first point
            draw_line(pixels, width, height, x0, y0, x1, y1, white)

        center = self.find_center_point(points_2d)

        flood_fill(pixels, center[0], center[1], width, height)
        # Step 5: Assign modified pixels back to the image and save it
        image.pixels[:] = pixels  # Apply the modified pixel data back to the image
        image.filepath_raw = os.path.join(bpy.app.tempdir, "image_mask.png")
        image.file_format = "PNG"
        image.save()
        ret_path = image.filepath_raw
        bpy.data.images.remove(image)
        return ret_path

    def set_texture_painting_mode(self):
        if bpy.context.active_object is not None:
            # Check if the object is a mesh
            if bpy.context.active_object.type == "MESH":
                # Switch to Texture Paint mode
                bpy.ops.object.mode_set(mode="TEXTURE_PAINT")
            else:
                print("Active object is not a mesh.")
            bpy.ops.wm.tool_set_by_id(name="builtin_brush.Draw")

    def create_brush_from_scene(self, context):
        brush_tool = context.scene.control_net_brush_tool

        viewport_image_path = self.get_viewport_capture()

        # Check if the image exists
        if viewport_image_path is not None:
            mask_image_path = None
            if self.button_id == "create_brush_inpainting":
                mask_image_path = self.create_mask_from_annotation(viewport_image_path)
                if mask_image_path is None:
                    if context.scene.control_net_brush_tool.remove_tmp_files:
                        os.remove(viewport_image_path)
                    self.report({"ERROR"}, "Failed to get Annotation.")
                    return {"FINISHED"}

            images = self.send_request_to_sd(
                brush_tool, viewport_image_path, mask_image_path
            )

            if len(images) > 0:
                if context.scene.control_net_brush_tool.remove_tmp_files:
                    os.remove(viewport_image_path)
                    if mask_image_path is not None:
                        os.remove(mask_image_path)
                    if len(images) > 1:
                        os.remove(images[1])
                else:
                    print(f"file {viewport_image_path} not deleted")
                    if len(images) > 1:
                        print(f"file {images[1]} not deleted")
                self.create_brush(images[0], brush_tool)
                self.set_texture_painting_mode()
                self.report({"INFO"}, "Brush reated successfully.")
            else:
                print("Failed to get images from sd.")
                self.report({"ERROR"}, "Failed to get images from sd.")
        else:
            print("Failed to capture viewport.")
            self.report({"ERROR"}, "Failed to capture viewport.")
        return {"FINISHED"}

    def execute(self, context):
        if "create_brush" in self.button_id:
            return self.create_brush_from_scene(context)
        elif self.button_id == "get_models":
            return self.get_sd_models(context)


class SendToControlNetPanel(bpy.types.Panel):
    bl_label = "Send to Control Net"
    bl_idname = "TEXTUREPAINT_PT_custom_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Brush From SD"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        brush_tool = scene.control_net_brush_tool
        col = layout.column(align=True)
        col.label(text="Brush from SD:")
        col.prop(brush_tool, "remove_tmp_files")
        col.prop(brush_tool, "sd_api_ip")
        col.prop(brush_tool, "sd_api_port")
        op = col.operator("mesh.send_to_control_net", text="Get models")
        op.button_id = "get_models"
        col.prop(brush_tool, "sd_model")
        col.prop(brush_tool, "controlnet_model")
        col.prop(brush_tool, "depth_preprocessor")
        col.prop(brush_tool, "sd_prompt")
        col.prop(brush_tool, "sd_negative_prompt")
        col.prop(brush_tool, "image_width")
        col.prop(brush_tool, "image_height")
        col.prop(brush_tool, "denoising_strength")
        op = col.operator("mesh.send_to_control_net", text="Brush from txt2img")
        op.button_id = "create_brush_txt2img"
        op = col.operator("mesh.send_to_control_net", text="Brush from img2img")
        op.button_id = "create_brush_img2img"
        op = col.operator("mesh.send_to_control_net", text="Brush from Inpainting")
        op.button_id = "create_brush_inpainting"
        col.prop(brush_tool, "overlay_alpha")


# Register the classes
def register():
    bpy.utils.register_class(SdProperties)
    bpy.types.Scene.control_net_brush_tool = bpy.props.PointerProperty(
        type=SdProperties
    )
    bpy.utils.register_class(SendToControlNetOperator)
    bpy.utils.register_class(SendToControlNetPanel)


def unregister():
    bpy.utils.unregister_class(SendToControlNetOperator)
    bpy.utils.unregister_class(SendToControlNetPanel)
    del bpy.types.Scene.control_net_brush_tool
    bpy.utils.unregister_class(SdProperties)


if __name__ == "__main__":
    register()
