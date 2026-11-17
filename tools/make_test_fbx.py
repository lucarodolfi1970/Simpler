"""Builds a small ring assembly with a real hierarchy and exports it to FBX (test data)."""
import math, sys
import bpy

out = sys.argv[-1]
bpy.ops.wm.read_factory_settings(use_empty=True)
col = bpy.context.scene.collection

def empty(name, parent=None, loc=(0, 0, 0)):
    e = bpy.data.objects.new(name, None); col.objects.link(e); e.parent = parent; e.location = loc; return e

def mat(name, color, metallic=0.0, transmission=0.0, rough=0.2, ior=1.5):
    m = bpy.data.materials.new(name); m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (*color, 1); p.inputs["Metallic"].default_value = metallic
    p.inputs["Roughness"].default_value = rough; p.inputs["Transmission Weight"].default_value = transmission
    p.inputs["IOR"].default_value = ior
    return m

gold = mat("Gold18k", (1.0, 0.77, 0.34), metallic=1.0, rough=0.15)
stone = mat("Stone", (1, 1, 1), transmission=1.0, rough=0.0, ior=2.4)

ring = empty("Anello")
mount = empty("Montatura", ring)
bpy.ops.mesh.primitive_torus_add(major_radius=0.009, minor_radius=0.0012, major_segments=96, minor_segments=24)
shank = bpy.context.object; shank.name = "Gambo"; shank.parent = mount; shank.rotation_euler = (math.radians(90), 0, 0)
shank.location = (0, 0, 0.009); shank.data.materials.append(gold); bpy.ops.object.shade_smooth()
head = empty("Castone", mount, (0, 0, 0.0195))
bpy.ops.mesh.primitive_cylinder_add(radius=0.0004, depth=0.004, vertices=16)
prong = bpy.context.object; prong.name = "Griffa_01"; prong.parent = head; prong.data.materials.append(gold)
for i in range(4):
    p = prong if i == 0 else prong.copy()
    if i: col.objects.link(p); p.name = f"Griffa_0{i+1}"; p.parent = head
    a = math.radians(45 + 90 * i); p.location = (0.0028 * math.cos(a), 0.0028 * math.sin(a), 0.0015)
stones = empty("Pietre", ring)
bpy.ops.mesh.primitive_ico_sphere_add(radius=0.003, subdivisions=4)
gem = bpy.context.object; gem.name = "Diamante_Centrale"; gem.parent = stones; gem.location = (0, 0, 0.0215)
gem.scale = (1, 1, 0.75); gem.data.materials.append(stone); bpy.ops.object.shade_smooth()
bpy.ops.export_scene.fbx(filepath=out, object_types={"EMPTY", "MESH"}, use_mesh_modifiers=True, bake_space_transform=False)
print("FBX_WRITTEN", out, "instances share mesh:", prong.data.users)
