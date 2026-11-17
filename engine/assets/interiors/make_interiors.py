"""Simpler's rooms for the material type «Interni» (matedit.interior): each room is rendered with Cycles from in
front of its window, so the picture is the room as seen straight through the window. The camera stands outside at a
distance equal to the room's depth: the back wall then fills exactly the middle half of the picture (INTERIOR_BACK =
0.5 in matedit), the window edges the borders of the picture. Run with: blender -b -P make_interiors.py
Rooms: W 4 m, H 3 m, D 4 m (aspect of the picture 4:3)."""
import math
import os

import bpy

OUT = os.path.dirname(os.path.abspath(__file__))
W, H, D = 4.0, 3.0, 4.0


def mat(name, rgb, rough=0.6, emit=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1.0)
    b.inputs["Roughness"].default_value = rough
    if emit > 0:
        b.inputs["Emission Color"].default_value = (*rgb, 1.0)
        b.inputs["Emission Strength"].default_value = emit
    return m


def box(name, x0, x1, y0, y1, z0, z1, m):
    """A box in room coordinates: x across the window (0..W), y up (0..H), z into the room (0..D)."""
    bpy.ops.mesh.primitive_cube_add(size=1)
    o = bpy.context.object
    o.name = name
    # Blender: X across, Y into the room, Z up
    o.scale = (x1 - x0, z1 - z0, y1 - y0)
    o.location = ((x0 + x1) / 2 - W / 2, (z0 + z1) / 2, (y0 + y1) / 2)
    o.data.materials.append(m)
    return o


def room_test():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    t = 0.05
    wall = mat("wall", (0.72, 0.68, 0.6))
    back = mat("back", (0.55, 0.62, 0.66))
    floor = mat("floor", (0.35, 0.22, 0.12), 0.4)
    ceil = mat("ceil", (0.85, 0.85, 0.83))
    sofa = mat("sofa", (0.25, 0.3, 0.45), 0.8)
    wood = mat("wood", (0.4, 0.26, 0.15), 0.5)
    art = mat("art", (0.8, 0.45, 0.2), 0.4)
    lamp = mat("lamp", (1.0, 0.85, 0.6), 0.5, emit=6.0)
    box("floor", 0, W, -t, 0, 0, D, floor)
    box("ceiling", 0, W, H, H + t, 0, D, ceil)
    box("left", -t, 0, 0, H, 0, D, wall)
    box("right", W, W + t, 0, H, 0, D, wall)
    box("back", 0, W, 0, H, D, D + t, back)
    box("sofa", 0.8, 3.2, 0, 0.45, 3.1, 3.95, sofa)
    box("sofa_back", 0.8, 3.2, 0.45, 0.85, 3.75, 3.95, sofa)
    box("table", 1.5, 2.5, 0.35, 0.4, 2.0, 2.7, wood)
    box("shelf", 3.6, 3.95, 0, 2.0, 0.6, 2.4, wood)
    box("art", 1.4, 2.6, 1.3, 2.1, D - 0.02, D, art)
    box("lamp", 1.7, 2.3, H - 0.1, H, 1.7, 2.3, lamp)
    lt = bpy.data.lights.new("fill", "AREA")
    lt.energy = 600
    lt.size = 2.0
    lo = bpy.data.objects.new("fill", lt)
    lo.location = (0, D / 2, H - 0.2)
    sc.collection.objects.link(lo)
    cam = bpy.data.cameras.new("cam")
    cam.sensor_fit = "HORIZONTAL"
    cam.angle = 2 * math.atan((W / 2) / D)        # the window fills the picture across
    co = bpy.data.objects.new("cam", cam)
    co.location = (0, -D, H / 2)
    co.rotation_euler = (math.pi / 2, 0, 0)
    sc.collection.objects.link(co)
    sc.camera = co
    sc.render.engine = "CYCLES"
    sc.cycles.samples = 64
    sc.cycles.use_denoising = True
    sc.render.resolution_x, sc.render.resolution_y = 1024, 768
    sc.view_settings.view_transform = "AgX"
    sc.world = bpy.data.worlds.new("w")
    sc.world.color = (0.05, 0.05, 0.05)
    sc.render.image_settings.file_format = "JPEG"
    sc.render.image_settings.quality = 88
    sc.render.filepath = os.path.join(OUT, "room_test.jpg")
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    room_test()
