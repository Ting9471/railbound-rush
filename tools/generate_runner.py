import bpy
import math
import os
from mathutils import Vector

# Original lightweight chibi runner generator for Blender 5.2+
# Coordinate system: Z up, character faces -Y.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(ROOT, "public", "models", "runner.glb")

# ---------- scene ----------
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
for datablocks in (bpy.data.meshes, bpy.data.curves, bpy.data.materials):
    pass

scene = bpy.context.scene
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 1.0
scene.render.engine = "BLENDER_EEVEE"
scene.world.color = (0.035, 0.045, 0.065)

# Palette is intentionally logo-free.
def material(name, hex_color, roughness=0.68, metallic=0.0):
    c = tuple(int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4))
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*c, 1.0)
    m.use_nodes = True
    bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf:
        base = bsdf.inputs.get("Base Color")
        rough = bsdf.inputs.get("Roughness")
        metal = bsdf.inputs.get("Metallic")
        if base: base.default_value = (*c, 1.0)
        if rough: rough.default_value = roughness
        if metal: metal.default_value = metallic
    return m

ORANGE = material("Jacket Orange", "F2752C", 0.58)
ORANGE_DARK = material("Orange Trim", "C84C1E", 0.56)
NAVY = material("Deep Navy", "172640", 0.62)
NAVY_SOFT = material("Navy Fabric", "243858", 0.76)
WHITE = material("Warm White", "F6F2E8", 0.64)
SKIN = material("Warm Skin", "EFB08A", 0.72)
SKIN_DARK = material("Skin Shadow", "CE876A", 0.73)
BROWN = material("Swept Brown Hair", "553325", 0.7)
BROWN_LIGHT = material("Hair Highlight", "7A4A2E", 0.66)
GRAY = material("Backpack Gray", "66717C", 0.78)
GRAY_DARK = material("Backpack Straps", "3E4854", 0.8)
BLACK = material("Eye Black", "151B24", 0.55)
SOLE = material("Sole Rubber", "D6D9D8", 0.82)


def apply_material(obj, mat):
    if obj.data and hasattr(obj.data, "materials"):
        obj.data.materials.append(mat)


def bevel(obj, amount=0.05, segments=2):
    if obj.type != "MESH":
        return
    mod = obj.modifiers.new("Soft bevel", "BEVEL")
    mod.width = amount
    mod.segments = segments
    mod.limit_method = "ANGLE"
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=mod.name)
    obj.select_set(False)


def smooth(obj):
    if obj.type == "MESH":
        for p in obj.data.polygons:
            p.use_smooth = True


def set_parent_keep_world(o, parent):
    """Parent while baking the authored world transform into true local space."""
    bpy.context.view_layer.update()
    world = o.matrix_world.copy()
    o.parent = parent
    o.matrix_parent_inverse.identity()
    o.matrix_basis = parent.matrix_world.inverted() @ world


def empty(name, loc=(0, 0, 0), parent=None):
    o = bpy.data.objects.new(name, None)
    o.empty_display_type = "SPHERE"
    o.empty_display_size = 0.08
    o.location = loc
    bpy.context.collection.objects.link(o)
    if parent:
        set_parent_keep_world(o, parent)
    return o


def cube(name, loc, scale, mat, parent=None, bevel_amt=0.05, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(location=loc, rotation=rot)
    o = bpy.context.object
    o.name = name
    o.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bevel(o, bevel_amt)
    apply_material(o, mat)
    if parent:
        set_parent_keep_world(o, parent)
    return o


def uv_sphere(name, loc, scale, mat, parent=None, segments=20, rings=12):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segments, ring_count=rings, location=loc)
    o = bpy.context.object
    o.name = name
    o.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    apply_material(o, mat)
    smooth(o)
    if parent:
        set_parent_keep_world(o, parent)
    return o


def cylinder(name, loc, radius, depth, mat, parent=None, rot=(0, 0, 0), vertices=16, scale=(1, 1, 1)):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=loc, rotation=rot)
    o = bpy.context.object
    o.name = name
    o.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bevel(o, min(0.035, radius * 0.25), 2)
    apply_material(o, mat)
    smooth(o)
    if parent:
        set_parent_keep_world(o, parent)
    return o


def torus(name, loc, major, minor, mat, parent=None, rot=(0, 0, 0), major_segments=20):
    bpy.ops.mesh.primitive_torus_add(major_radius=major, minor_radius=minor, major_segments=major_segments, minor_segments=8, location=loc, rotation=rot)
    o = bpy.context.object
    o.name = name
    apply_material(o, mat)
    smooth(o)
    if parent:
        set_parent_keep_world(o, parent)
    return o


def limb_between(name, a, b, radius, mat, parent):
    a, b = Vector(a), Vector(b)
    mid = (a + b) / 2
    vec = b - a
    o = cylinder(name, mid, radius, vec.length, mat, parent=parent, vertices=14)
    o.rotation_mode = "QUATERNION"
    o.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(vec.normalized())
    return o


def wedge(name, verts, faces, mat, parent=None, loc=(0, 0, 0), rot=(0, 0, 0)):
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    o = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(o)
    o.location = loc
    o.rotation_euler = rot
    apply_material(o, mat)
    bevel(o, 0.025, 2)
    if parent:
        set_parent_keep_world(o, parent)
    return o

# ---------- hierarchy / procedural pivots ----------
root = empty("Runner_ROOT", (0, 0, 0))
root["asset_type"] = "original_chibi_runner"
root["animation_note"] = "Rotate named *_PIVOT empties for procedural animation"
hips = empty("Hips_PIVOT", (0, 0, 1.14), root)
torso_pivot = empty("Torso_PIVOT", (0, 0, 1.2), hips)
head_pivot = empty("Head_PIVOT", (0, 0, 2.25), torso_pivot)

# Legs: slightly bent, feet planted.
def make_leg(side, x, phase):
    hip = empty(f"{side}_Hip_PIVOT", (x, 0, 1.12), hips)
    knee = empty(f"{side}_Knee_PIVOT", (x, -0.015 * phase, 0.68), hip)
    ankle = empty(f"{side}_Ankle_PIVOT", (x, -0.01, 0.23), knee)
    limb_between(f"{side}_Thigh", (x, 0, 1.08), (x, -0.015 * phase, 0.69), 0.145, NAVY_SOFT, hip)
    limb_between(f"{side}_Shin", (x, -0.015 * phase, 0.68), (x, -0.02, 0.27), 0.13, NAVY, knee)
    # White side stripe along outside of joggers.
    stripe_x = x + (-0.137 if side == "Left" else 0.137)
    limb_between(f"{side}_Jogger_White_Stripe", (stripe_x, -0.01, 1.01), (stripe_x, -0.02, 0.37), 0.025, WHITE, hip)
    # chunky sneaker facing forward (-Y)
    cube(f"{side}_Sneaker_Upper", (x, -0.115, 0.16), (0.19, 0.34, 0.12), WHITE, ankle, 0.06)
    cube(f"{side}_Sneaker_Navy_Heel", (x, 0.10, 0.18), (0.195, 0.13, 0.10), NAVY, ankle, 0.04)
    cube(f"{side}_Sneaker_Orange_Toe", (x, -0.335, 0.17), (0.195, 0.12, 0.09), ORANGE, ankle, 0.045)
    cube(f"{side}_Sneaker_Sole", (x, -0.12, 0.065), (0.215, 0.36, 0.055), SOLE, ankle, 0.035)
    # two clean lace bars, no logos
    for yi in (-0.18, -0.27):
        cube(f"{side}_Lace_{yi}", (x, yi, 0.285), (0.13, 0.018, 0.012), NAVY, ankle, 0.008)
    return hip

make_leg("Left", -0.205, -1)
make_leg("Right", 0.205, 1)

# Torso: overlapping soft volumes give the jacket a puffed, organic silhouette.
uv_sphere("Jacket_Body", (0, 0, 1.62), (0.54, 0.31, 0.58), ORANGE, torso_pivot, 24, 14)
uv_sphere("Jacket_Left_Puff", (-0.42, -0.005, 1.66), (0.20, 0.285, 0.43), ORANGE, torso_pivot, 18, 12)
uv_sphere("Jacket_Right_Puff", (0.42, -0.005, 1.66), (0.20, 0.285, 0.43), ORANGE, torso_pivot, 18, 12)
cylinder("Jacket_Navy_Hem", (0, -0.015, 1.17), 0.46, 0.15, NAVY, torso_pivot, vertices=24, scale=(1, 0.63, 1))
uv_sphere("Jacket_White_Chest_Panel", (0, -0.296, 1.62), (0.275, 0.025, 0.265), WHITE, torso_pivot, 20, 12)
uv_sphere("Jacket_Navy_Yoke", (0, -0.319, 1.87), (0.40, 0.027, 0.105), NAVY, torso_pivot, 20, 10)
cylinder("Jacket_Zipper", (0, -0.327, 1.54), 0.018, 0.68, NAVY, torso_pivot, vertices=12)
for x in (-0.34, 0.34):
    cylinder("Pocket_Trim_L" if x < 0 else "Pocket_Trim_R", (x, -0.307, 1.43), 0.025, 0.24, WHITE, torso_pivot, rot=(0, (-0.20 if x < 0 else 0.20), 0), vertices=12)

# Hood behind neck, formed by layered rounded shapes.
torus("Hood_Rim", (0, 0.04, 2.05), 0.34, 0.105, ORANGE_DARK, torso_pivot, rot=(math.radians(90), 0, 0))
uv_sphere("Hood_Back", (0, 0.17, 2.05), (0.43, 0.22, 0.42), ORANGE, torso_pivot, 20, 12)

# Backpack and straps.
cube("Backpack_Main", (0, 0.36, 1.61), (0.42, 0.18, 0.48), GRAY, torso_pivot, 0.10)
cube("Backpack_Pocket", (0, 0.525, 1.47), (0.30, 0.065, 0.21), GRAY_DARK, torso_pivot, 0.055)
cube("Backpack_Top_Handle", (0, 0.46, 2.05), (0.13, 0.025, 0.07), GRAY_DARK, torso_pivot, 0.025)
for x in (-0.38, 0.38):
    limb_between("Backpack_Strap_L" if x < 0 else "Backpack_Strap_R", (x, -0.10, 1.94), (x * 0.88, -0.18, 1.35), 0.035, GRAY_DARK, torso_pivot)

# Arms, with proper shoulder/elbow pivots and a relaxed running bend.
def make_arm(side, x, direction):
    shoulder = empty(f"{side}_Shoulder_PIVOT", (x, 0, 1.87), torso_pivot)
    elbow_pos = (x + 0.08 * direction, -0.12 * direction, 1.50)
    wrist_pos = (x - 0.01 * direction, -0.28 * direction, 1.27)
    elbow = empty(f"{side}_Elbow_PIVOT", elbow_pos, shoulder)
    wrist = empty(f"{side}_Wrist_PIVOT", wrist_pos, elbow)
    limb_between(f"{side}_Jacket_UpperArm", (x, 0, 1.85), elbow_pos, 0.16, ORANGE, shoulder)
    limb_between(f"{side}_Jacket_Forearm", elbow_pos, wrist_pos, 0.145, ORANGE, elbow)
    cylinder(f"{side}_Navy_Cuff", wrist_pos, 0.15, 0.10, NAVY, wrist, vertices=16)
    uv_sphere(f"{side}_Hand", (wrist_pos[0], wrist_pos[1] - 0.035 * direction, wrist_pos[2] - 0.11), (0.135, 0.12, 0.15), SKIN, wrist, 16, 10)

make_arm("Left", -0.53, -1)
make_arm("Right", 0.53, 1)

# Head and ears.
uv_sphere("Head", (0, -0.02, 2.31), (0.43, 0.37, 0.46), SKIN, head_pivot, 28, 18)
uv_sphere("Left_Ear", (-0.39, -0.015, 2.31), (0.08, 0.055, 0.13), SKIN_DARK, head_pivot, 16, 10)
uv_sphere("Right_Ear", (0.39, -0.015, 2.31), (0.08, 0.055, 0.13), SKIN_DARK, head_pivot, 16, 10)

# Friendly minimal face on forward (-Y) surface.
for x in (-0.145, 0.145):
    uv_sphere("Left_Eye" if x < 0 else "Right_Eye", (x, -0.365, 2.35), (0.045, 0.022, 0.062), BLACK, head_pivot, 12, 8)
    uv_sphere("Left_Eye_Glint" if x < 0 else "Right_Eye_Glint", (x - 0.012, -0.385, 2.37), (0.011, 0.008, 0.014), WHITE, head_pivot, 8, 6)
cube("Nose", (0, -0.388, 2.26), (0.022, 0.012, 0.028), SKIN_DARK, head_pivot, 0.01)
# small smile curve
curve = bpy.data.curves.new("SmileCurve", "CURVE")
curve.dimensions = "3D"
curve.bevel_depth = 0.009
curve.bevel_resolution = 2
spline = curve.splines.new("BEZIER")
spline.bezier_points.add(2)
for p, co in zip(spline.bezier_points, [(-0.055, -0.389, 2.205), (0, -0.405, 2.19), (0.055, -0.389, 2.205)]):
    p.co = co
    p.handle_left_type = p.handle_right_type = "AUTO"
smile = bpy.data.objects.new("Smile", curve)
curve.materials.append(BLACK)
bpy.context.collection.objects.link(smile)
set_parent_keep_world(smile, head_pivot)

# Brown swept hair: cap plus deliberately asymmetrical locks.
uv_sphere("Hair_Cap", (0, 0.005, 2.58), (0.445, 0.365, 0.28), BROWN, head_pivot, 24, 14)
locks = [
    (-0.28, -0.31, 2.57, -14, 0.16), (-0.12, -0.36, 2.61, -7, 0.18),
    (0.05, -0.37, 2.63, 9, 0.20), (0.22, -0.33, 2.60, 22, 0.19),
    (0.33, -0.22, 2.55, 32, 0.15)
]
for i, (x, y, z, ang, length) in enumerate(locks):
    # tapered six-sided lock made as a small wedge
    verts = [(-0.07, 0, 0.08), (0.07, 0, 0.08), (0.055, 0.035, 0.07), (-0.055, 0.035, 0.07),
             (-0.018, 0, -length), (0.018, 0, -length), (0.012, 0.025, -length), (-0.012, 0.025, -length)]
    faces = [(0,1,2,3),(4,7,6,5),(0,4,5,1),(1,5,6,2),(2,6,7,3),(3,7,4,0)]
    wedge(
        f"Swept_Hair_Lock_{i+1}", verts, faces,
        BROWN_LIGHT if i in (2,3) else BROWN, head_pivot,
        loc=(x, y, z), rot=(0, math.radians(ang), 0),
    )

# Large headphones: navy arch with orange ear cups.
torus("Headphone_Band", (0, 0.015, 2.51), 0.43, 0.055, NAVY, head_pivot, rot=(math.radians(90), 0, 0), major_segments=24)
for side, x in (("Left", -0.43), ("Right", 0.43)):
    hp = empty(f"{side}_Headphone_PIVOT", (x, -0.005, 2.34), head_pivot)
    cylinder(f"{side}_Headphone_Cup", (x, -0.005, 2.34), 0.145, 0.095, ORANGE, hp, rot=(0, math.radians(90), 0), vertices=20, scale=(1, 1, 1.18))
    cylinder(f"{side}_Headphone_Cushion", (x + (-0.055 if x < 0 else 0.055), -0.005, 2.34), 0.112, 0.045, NAVY, hp, rot=(0, math.radians(90), 0), vertices=20)
    cylinder(f"{side}_Headphone_Disc", (x + (0.052 if x < 0 else -0.052), -0.005, 2.34), 0.082, 0.022, WHITE, hp, rot=(0, math.radians(90), 0), vertices=20)

# Subtle ground contact marker, excluded from export.
bpy.ops.mesh.primitive_circle_add(vertices=32, radius=0.46, fill_type="NGON", location=(0, 0, 0.006))
marker = bpy.context.object
marker.name = "Preview_Ground_Marker"
marker.hide_render = True
marker.hide_viewport = True

# Custom properties to make pivots discoverable.
for o in bpy.data.objects:
    if o.name.endswith("_PIVOT") or o.name == "Runner_ROOT":
        o["procedural_pivot"] = True

# Select only the character hierarchy, not preview helpers.
bpy.ops.object.select_all(action="DESELECT")
export_objects = [root, *root.children_recursive]
for o in export_objects:
    o.select_set(True)
bpy.context.view_layer.objects.active = root
bpy.context.view_layer.update()

pivot_names = sorted(o.name for o in export_objects if o.name.endswith("_PIVOT"))
expected_pivots = {
    name: (bpy.data.objects[name].matrix_world.translation.copy(),
           bpy.data.objects[name].parent.name if bpy.data.objects[name].parent else None)
    for name in pivot_names
}
mesh_count = sum(1 for o in export_objects if o.type == "MESH")
vert_count = sum(len(o.data.vertices) for o in export_objects if o.type == "MESH")
triangle_count = sum(len(o.data.loop_triangles) for o in export_objects if o.type == "MESH")

os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
bpy.ops.export_scene.gltf(
    filepath=OUTPUT,
    export_format="GLB",
    use_selection=True,
    export_apply=False,
    export_yup=True,
    export_materials="EXPORT",
    export_attributes=False,
    export_extras=True,
    export_cameras=False,
    export_lights=False,
)

# Reimport the actual deliverable and validate hierarchy, pivots, and head attachments.
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.gltf(filepath=OUTPUT)
bpy.context.view_layer.update()

errors = []
imported_root = bpy.data.objects.get("Runner_ROOT")
if not imported_root:
    errors.append("missing Runner_ROOT")
elif imported_root.get("asset_type") != "original_chibi_runner":
    errors.append("Runner_ROOT identity property changed")

for name, (expected_location, expected_parent) in expected_pivots.items():
    pivot = bpy.data.objects.get(name)
    if not pivot:
        errors.append(f"missing pivot {name}")
        continue
    delta = (pivot.matrix_world.translation - expected_location).length
    if delta > 0.001:
        errors.append(f"pivot moved {name} ({delta:.6f}m)")
    actual_parent = pivot.parent.name if pivot.parent else None
    if actual_parent != expected_parent:
        errors.append(f"pivot parent changed {name} ({actual_parent} != {expected_parent})")


def world_bounds(obj):
    points = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    return Vector(map(min, zip(*points))), Vector(map(max, zip(*points)))


head = bpy.data.objects.get("Head")
hair_cap = bpy.data.objects.get("Hair_Cap")
if not head or not hair_cap:
    errors.append("missing head attachment geometry")
else:
    head_min, head_max = world_bounds(head)
    cap_min, cap_max = world_bounds(hair_cap)
    for name in sorted(o.name for o in bpy.data.objects if o.name.startswith("Swept_Hair_Lock_")):
        lock_min, lock_max = world_bounds(bpy.data.objects[name])
        margin = 0.04
        overlaps_cap = all(
            lock_max[i] >= cap_min[i] - margin and lock_min[i] <= cap_max[i] + margin
            for i in range(3)
        )
        if not overlaps_cap:
            errors.append(f"detached hair geometry {name}")

    head_center = (head_min + head_max) / 2
    for obj in (o for o in bpy.data.objects if o.type == "MESH"):
        obj_min, obj_max = world_bounds(obj)
        if obj_min.z <= head_max.z + 0.02:
            continue
        obj_center = (obj_min + obj_max) / 2
        if abs(obj_center.x - head_center.x) > 0.65 or abs(obj_center.y - head_center.y) > 0.65:
            errors.append(f"detached geometry above head {obj.name}")

if triangle_count > 20000:
    errors.append(f"triangle budget exceeded ({triangle_count})")
if errors:
    raise RuntimeError("RUNNER_VALIDATION_FAILED: " + "; ".join(errors))

print("RUNNER_EXPORT_OK")
print(f"Output: {OUTPUT}")
print(f"Selected meshes: {mesh_count}")
print(f"Selected vertices: {vert_count}")
print(f"Selected triangles: {triangle_count}")
print(f"Validated pivots: {len(expected_pivots)}")
print("Detached geometry above head: 0")
print("Hair locks attached: 5/5")
print(f"File bytes: {os.path.getsize(OUTPUT)}")
print("RUNNER_REIMPORT_VALIDATION_OK")
