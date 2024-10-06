bl_info = {
    "name": "Stencil Brush from Depth ControlNet",
    "blender": (4, 2, 2),
    "category": "Object",
    "version": (0, 0, 1),
    "author": "Wojciech Michna",
    "description": "Create stencil brush using Depth ControlNet",
}

import bpy
import os
import urllib.request
import json
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


class SendToControlNetOperator(bpy.types.Operator):
    bl_idname = "mesh.send_to_control_net"
    bl_label = "Send to Control Net"
    bl_description = "Send current view to Control Net"

    button_id: bpy.props.StringProperty()

    def create_brush(self, image_path):
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

        print("New stencil brush created and set as active.")

    def send_request_to_sd(self, brush_tool, image_path):
        if "txt2img" in self.button_id:
            url = f"http://{brush_tool.sd_api_ip}:{brush_tool.sd_api_port}/sdapi/v1/txt2img"
        elif "img2img" in self.button_id:
            url = f"http://{brush_tool.sd_api_ip}:{brush_tool.sd_api_port}/sdapi/v1/img2img"

        # Define the headers
        headers = {
            "Accept": "*/*",
            "Accept-Encoding": "deflate, gzip",
            "Content-Type": "application/json",
        }

        image_path = image_path
        with open(image_path, "rb") as img_file:
            base64_image = base64.b64encode(img_file.read()).decode("utf-8")

        # Define the data payload
        data = {
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

        if "img2img" in self.button_id:
            data["init_images"] = [base64_image]

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
                        previous_state = space.overlay.show_overlays
                        space.overlay.show_overlays = False
                        # Capture the viewport using OpenGL without saving to a file
                        bpy.ops.render.opengl(write_still=False, view_context=True)
                        space.overlay.show_overlays = previous_state

        # Access the 'Render Result' image
        render_result = bpy.data.images.get("Render Result")
        # Check if the image exists
        if render_result:
            # Save the image manually to the specified path
            render_result.save_render(filepath=output_path)
            return output_path
        else:
            return None

    def create_brush_from_scene(self, context):
        brush_tool = context.scene.control_net_brush_tool

        viewport_image_path = self.get_viewport_capture()
        # Check if the image exists
        if viewport_image_path is not None:
            images = self.send_request_to_sd(brush_tool, viewport_image_path)
            if len(images) > 0:
                if context.scene.control_net_brush_tool.remove_tmp_files:
                    os.remove(viewport_image_path)
                    if len(images) > 1:
                        os.remove(images[1])
                else:
                    print(f"file {viewport_image_path} not deleted")
                    if len(images) > 1:
                        print(f"file {images[1]} not deleted")
                self.create_brush(images[0])
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
