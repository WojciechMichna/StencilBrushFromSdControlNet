# StencilBrushFromSdControlNet
Blender plugin which creates stencil brush in texture painting mode using Stable Diffusion and control net depth model
The plugin sends the current 3D view to the running SD instance. The 3D view is used as control net depth input to generate a new stencil brush for texture painting.

## Prerequisites
Running stable-diffusion-webui API with controlnet installed and depth model download.
The script does not start stable-diffusion-webui, it just connects to the existing one.
You will need to start the webui with --api for the script to be able to connect.
## Installation
In blender preferences in Add-ons tab chose "Install from Disk..." and navigate to "stencil_from_control_net.py" location and chose the "stencil_from_control_net.py" file 
## Features
-  Create a stencil brush from the current view by sending the current view to SD txt2img
-  Create a stencil brush from the current view by sending the current view to SD img2img
## How to Use
1. In Texture Paint mode open "Brush From SD" tab.
2. Set IP of running SD instance.
3. Click "Get Models"
4. Set SD model and Control Net model
5. Press "Send to sd"

## Demo
Basic workflow example, after connecting to SD API, we get available models set the SD model and control net model then we generate first brush with txt2img and next brush with img2img
[Toy Car.webm](https://github.com/user-attachments/assets/045fa68c-c8de-42b8-9da0-705c71c7b089)
Second example, we create first brush with txt2img and next brushes with img2img
[Castle Example.webm](https://github.com/user-attachments/assets/4c01a9f5-6a88-4535-aab9-72f38d84de24)
