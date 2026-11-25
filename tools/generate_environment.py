import bpy
import math
import os
from mathutils import Vector

# Lightweight visual-only ancient Chinese railway scenery chunk for Blender 5.2+.
# Authoring coordinates are metric and Z-up. The GLB exporter converts to glTF Y-up.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(ROOT, "public", "models", "environment", "ancient_railway.glb")
PLAYABLE_HALF_WIDTH = 6.0

# ---------- clean metric scene ----------
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
for collection in (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
    for datablock in list(collection):
        collection.remove(datablock)

scene = bpy.context.scene
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 1.0
scene.render.engine = "BLENDER_EEVEE"


def material(name, hex_color, roughness=0.72, metallic=0.0):
    color = tuple(int(hex_color[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1.0)
    mat.use_nodes = True
    bsdf = next((node for node in mat.node_tree.nodes if node.type == "BSDF_PRINCIPLED"), None)
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic
    return mat


PLASTER = material("Warm White Plaster", "E9DDC7", 0.86)
PLASTER_SHADE = material("Plaster Shadow", "CDBD9F", 0.88)
TEAL = material("Glazed Teal Tile", "1D716F", 0.48)
TEAL_DARK = material("Deep Teal Eaves", "174F50", 0.58)
VERMILION = material("Vermilion Lacquer", "B83C2F", 0.56)
VERMILION_DARK = material("Vermilion Shade", "7F2B27", 0.68)
GOLD = material("Warm Brass", "D6A443", 0.48, 0.18)
LANTERN = material("Lantern Red", "D94B3F", 0.42)
STONE = material("Blue Gray Stone", "758486", 0.9)
STONE_DARK = material("Dark Path Stone", "526365", 0.92)
WOOD = material("Warm Wood", "6A4331", 0.78)
BAMBOO = material("Bamboo Green", "547A48", 0.78)
BAMBOO_LIGHT = material("Bamboo Leaf", "74965A", 0.76)
SOIL = material("Planter Soil", "4C3B2E", 0.95)


def set_parent_keep_world(obj, parent):
    world = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_world = world


def empty(name, location=(0, 0, 0), parent=None):
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = "PLAIN_AXES"
    obj.empty_display_size = 0.35
    obj.location = location
    bpy.context.collection.objects.link(obj)
    if parent:
        set_parent_keep_world(obj, parent)
    return obj


def apply_material(obj, mat):
    obj.data.materials.append(mat)


def bevel(obj, width=0.06, segments=2):
    if obj.type != "MESH" or width <= 0:
        return
    modifier = obj.modifiers.new("Rounded edges", "BEVEL")
    modifier.width = width
    modifier.segments = segments
    modifier.limit_method = "ANGLE"
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    obj.select_set(False)


def cube(name, location, dimensions, mat, parent, bevel_width=0.06, rotation=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(location=location, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bevel(obj, min(bevel_width, min(dimensions) * 0.22), 2)
    apply_material(obj, mat)
    set_parent_keep_world(obj, parent)
    return obj


def cylinder(name, location, radius, depth, mat, parent, vertices=12, rotation=(0, 0, 0), bevel_width=0.035):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=location, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    bevel(obj, bevel_width, 2)
    apply_material(obj, mat)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    set_parent_keep_world(obj, parent)
    return obj


def roof(name, location, width, length, height, mat, parent):
    """Low-poly hipped roof with a strong upturned Chinese-eave silhouette."""
    x, y, z = location
    inset = min(1.0, width * 0.15, length * 0.18)
    verts = [
        (-width / 2, -length / 2, 0), (width / 2, -length / 2, 0),
        (width / 2, length / 2, 0), (-width / 2, length / 2, 0),
        (-width / 2 + inset, -length / 2 + inset, height),
        (width / 2 - inset, -length / 2 + inset, height),
        (width / 2 - inset, length / 2 - inset, height),
        (-width / 2 + inset, length / 2 - inset, height),
    ]
    faces = [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7), (4, 5, 6, 7), (0, 3, 2, 1)]
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = (x, y, z)
    bpy.context.collection.objects.link(obj)
    apply_material(obj, mat)
    bevel(obj, 0.055, 2)
    set_parent_keep_world(obj, parent)
    # dark eave band and raised ridge provide detail without dense roof tiles
    cube(name + "_EaveBand", (x, y, z + 0.02), (width + 0.06, length + 0.06, 0.16), TEAL_DARK, parent, 0.045)
    cube(name + "_Ridge", (x, y, z + height + 0.06), (0.15, max(0.25, length - 2 * inset), 0.16), TEAL_DARK, parent, 0.045)
    return obj


def lantern(name, location, parent, scale=1.0):
    x, y, z = location
    cylinder(name + "_Cord", (x, y, z + 0.58 * scale), 0.025 * scale, 0.55 * scale, WOOD, parent, vertices=8, bevel_width=0.01)
    cylinder(name + "_Top", (x, y, z + 0.30 * scale), 0.22 * scale, 0.10 * scale, GOLD, parent, vertices=12, bevel_width=0.02)
    body = cylinder(name + "_Body", (x, y, z), 0.34 * scale, 0.58 * scale, LANTERN, parent, vertices=16, bevel_width=0.07)
    body.scale.x = 0.88
    body.scale.y = 0.88
    cylinder(name + "_Bottom", (x, y, z - 0.31 * scale), 0.19 * scale, 0.09 * scale, GOLD, parent, vertices=12, bevel_width=0.02)
    cylinder(name + "_Tassel", (x, y, z - 0.55 * scale), 0.035 * scale, 0.42 * scale, VERMILION_DARK, parent, vertices=8, bevel_width=0.01)


def planter(name, x, y, parent):
    cube(name + "_Base", (x, y, 0.35), (1.7, 1.35, 0.70), STONE, parent, 0.14)
    cube(name + "_Lip", (x, y, 0.74), (1.9, 1.55, 0.18), STONE_DARK, parent, 0.07)
    cube(name + "_Soil", (x, y, 0.86), (1.52, 1.18, 0.10), SOIL, parent, 0.03)


def bamboo_cluster(name, x, y, parent, mirror=1):
    planter(name + "_Planter", x, y, parent)
    stems = [(-0.42, -0.22, 3.9, -4), (0.0, 0.12, 4.9, 2), (0.38, -0.05, 4.35, 5)]
    for index, (dx, dy, height, tilt) in enumerate(stems):
        sx = x + dx
        sy = y + dy
        cylinder(f"{name}_Stem_{index + 1}", (sx, sy, 0.82 + height / 2), 0.085, height, BAMBOO, parent, vertices=10, rotation=(math.radians(tilt), 0, 0), bevel_width=0.02)
        for node in range(1, int(height / 0.72)):
            z = 0.82 + node * 0.72
            cylinder(f"{name}_Node_{index + 1}_{node}", (sx, sy, z), 0.105, 0.055, BAMBOO_LIGHT, parent, vertices=10, bevel_width=0.012)
        for leaf_index, z in enumerate((2.3, 3.05, 3.72, 4.25)):
            if z > height + 0.55:
                continue
            side = mirror * (-1 if (leaf_index + index) % 2 else 1)
            cube(
                f"{name}_Leaf_{index + 1}_{leaf_index + 1}",
                (sx + side * 0.34, sy + 0.05 * leaf_index, z),
                (0.62, 0.10, 0.20), BAMBOO_LIGHT, parent, 0.07,
                rotation=(0, math.radians(side * 20), math.radians(side * 15)),
            )


def building(name, side, y, width, length, wall_height, parent):
    # Inner facade edge always remains beyond x +/- 7.1 m.
    inner = 7.25
    center_x = side * (inner + width / 2)
    cube(name + "_Plinth", (center_x, y, 0.24), (width + 0.45, length + 0.35, 0.48), STONE, parent, 0.12)
    cube(name + "_Walls", (center_x, y, 0.48 + wall_height / 2), (width, length, wall_height), PLASTER, parent, 0.12)
    # Timber frame and recessed panels face the lane.
    face_x = side * (inner - 0.03)
    for offset in (-length * 0.31, 0, length * 0.31):
        cube(name + f"_Post_{offset:+.1f}", (face_x, y + offset, 1.8), (0.20, 0.22, 2.75), VERMILION_DARK, parent, 0.045)
    cube(name + "_Sill", (face_x, y, 0.95), (0.22, length * 0.78, 0.17), WOOD, parent, 0.04)
    cube(name + "_Lintel", (face_x, y, 2.92), (0.23, length * 0.78, 0.20), VERMILION, parent, 0.045)
    for offset in (-length * 0.17, length * 0.17):
        cube(name + f"_Window_{offset:+.1f}", (face_x - side * 0.03, y + offset, 1.92), (0.10, 1.12, 1.18), TEAL_DARK, parent, 0.06)
        for bar in (-0.34, 0, 0.34):
            cube(name + f"_WindowBar_{offset:+.1f}_{bar:+.2f}", (face_x - side * 0.09, y + offset + bar, 1.92), (0.11, 0.045, 1.03), WOOD, parent, 0.015)
    roof(name + "_Roof", (center_x, y, 0.48 + wall_height), width + 1.15, length + 1.05, 1.15, TEAL, parent)
    # Small warm-white upper pavilion creates a layered skyline.
    if width >= 4.6:
        cube(name + "_Upper", (center_x + side * 0.15, y, wall_height + 1.9), (width * 0.58, length * 0.58, 1.65), PLASTER_SHADE, parent, 0.10)
        roof(name + "_UpperRoof", (center_x + side * 0.15, y, wall_height + 2.72), width * 0.58 + 0.9, length * 0.58 + 0.8, 0.88, TEAL, parent)


def gate_side(name, side, y, parent):
    """Paired vermilion gate towers frame the lane without any cross-lane solid beam."""
    x = side * 7.15
    cube(name + "_StoneFoot", (x, y, 0.38), (1.45, 1.85, 0.76), STONE, parent, 0.16)
    cube(name + "_Pillar", (x, y, 3.32), (0.86, 0.90, 5.55), VERMILION, parent, 0.12)
    cube(name + "_CollarLow", (x, y, 1.15), (1.08, 1.10, 0.24), GOLD, parent, 0.055)
    cube(name + "_CollarHigh", (x, y, 5.55), (1.10, 1.12, 0.24), GOLD, parent, 0.055)
    # Inward cantilever ends at x +/-6.18, safely outside the playable width.
    cantilever_x = side * 6.67
    cube(name + "_InwardBracket", (cantilever_x, y, 5.83), (0.98, 0.72, 0.32), VERMILION_DARK, parent, 0.07)
    cube(name + "_GoldCap", (x, y, 6.05), (1.42, 1.42, 0.22), GOLD, parent, 0.065)
    roof(name + "_Canopy", (x, y, 6.15), 1.80, 2.45, 0.70, TEAL, parent)
    lantern(name + "_Lantern", (side * 7.02, y - 1.25, 4.55), parent, 0.85)


# ---------- authored modular chunk ----------
root = empty("Ancient_Railway_Environment_ROOT")
root["asset_type"] = "visual_only_modular_railway_scenery"
root["metric_length_m"] = 54.0
root["playable_clear_half_width_m"] = PLAYABLE_HALF_WIDTH
root["coordinate_note"] = "Authored Blender Z-up; exported glTF Y-up"
root["collision_note"] = "Visual scenery only; no gameplay collision metadata"

left = empty("Left_Scenery", parent=root)
right = empty("Right_Scenery", parent=root)

# Raised path edging delineates the track corridor but leaves x +/-6 completely clear.
for side, parent in ((-1, left), (1, right)):
    cube(f"{'Left' if side < 0 else 'Right'}_Path_Edge", (side * 6.42, 0, 0.18), (0.55, 54.0, 0.36), STONE_DARK, parent, 0.09)
    cube(f"{'Left' if side < 0 else 'Right'}_Walkway", (side * 7.70, 0, 0.11), (2.0, 54.0, 0.22), STONE, parent, 0.07)
    # Regular paving insets create readable motion rhythm.
    for index, y in enumerate(range(-24, 25, 4)):
        cube(f"{'Left' if side < 0 else 'Right'}_Paver_{index + 1}", (side * 7.20, y, 0.27), (0.55, 1.85, 0.09), PLASTER_SHADE, parent, 0.025)

# Building rhythm alternates scale and setback on both sides of the 54 m chunk.
for side, parent in ((-1, left), (1, right)):
    building(f"{'Left' if side < 0 else 'Right'}_South_House", side, -18.0, 4.5, 9.0, 3.65, parent)
    building(f"{'Left' if side < 0 else 'Right'}_Central_House", side, 0.5, 5.0, 10.5, 4.05, parent)
    building(f"{'Left' if side < 0 else 'Right'}_North_House", side, 19.2, 4.3, 8.6, 3.50, parent)

# Twin open gate sides form a landmark at the approach without crossing the lane.
gate_side("Left_Paifang", -1, -7.0, left)
gate_side("Right_Paifang", 1, -7.0, right)

# Alternating lanterns and greenery make the chunk lively while keeping silhouettes uncluttered.
for index, y in enumerate((-23.0, -13.0, 4.5, 13.5, 25.0)):
    side = -1 if index % 2 == 0 else 1
    parent = left if side < 0 else right
    lantern(f"Wayside_Lantern_{index + 1}", (side * 6.95, y, 2.10), parent, 0.78)

bamboo_cluster("Left_Bamboo_South", -8.0, -25.0, left, -1)
bamboo_cluster("Right_Bamboo_Central", 8.1, 9.5, right, 1)
bamboo_cluster("Left_Bamboo_North", -8.0, 25.0, left, -1)
bamboo_cluster("Right_Bamboo_North", 8.0, 25.2, right, 1)

# Low stone planters with compact ornamental shrubs.
for index, (x, y) in enumerate(((-8.0, -11.5), (8.0, -19.0), (-8.0, 11.0), (8.0, 19.0))):
    parent = left if x < 0 else right
    planter(f"Stone_Planter_{index + 1}", x, y, parent)
    cylinder(f"Shrub_Trunk_{index + 1}", (x, y, 1.25), 0.10, 0.8, WOOD, parent, vertices=10, bevel_width=0.02)
    for leaf_index, (dx, dy, dz) in enumerate(((-0.32, 0, 1.62), (0.30, 0.08, 1.68), (0, -0.18, 1.92))):
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.55, location=(x + dx, y + dy, dz))
        shrub = bpy.context.object
        shrub.name = f"Shrub_{index + 1}_Crown_{leaf_index + 1}"
        shrub.scale = (1.15, 0.82, 0.90)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        bevel(shrub, 0.035, 2)
        apply_material(shrub, BAMBOO_LIGHT if leaf_index == 2 else BAMBOO)
        set_parent_keep_world(shrub, parent)

# ---------- validation and export ----------
def world_bounds(objects):
    points = [obj.matrix_world @ Vector(corner) for obj in objects if obj.type == "MESH" for corner in obj.bound_box]
    minimum = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    maximum = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    return minimum, maximum


export_objects = [root, *root.children_recursive]
mesh_objects = [obj for obj in export_objects if obj.type == "MESH"]
violations = []
for obj in mesh_objects:
    xs = [(obj.matrix_world @ Vector(corner)).x for corner in obj.bound_box]
    if min(xs) < PLAYABLE_HALF_WIDTH and max(xs) > -PLAYABLE_HALF_WIDTH:
        violations.append((obj.name, min(xs), max(xs)))
if violations:
    raise RuntimeError(f"Playable corridor violation(s): {violations}")

minimum, maximum = world_bounds(mesh_objects)
dimensions = maximum - minimum
if not (42.0 <= dimensions.y <= 60.0):
    raise RuntimeError(f"Chunk length must be 42-60m, got {dimensions.y:.3f}m")
if bpy.data.cameras or bpy.data.lights:
    raise RuntimeError("Environment export must not contain cameras or lights")

bpy.ops.object.select_all(action="DESELECT")
for obj in export_objects:
    obj.select_set(True)
bpy.context.view_layer.objects.active = root
os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
bpy.ops.export_scene.gltf(
    filepath=OUTPUT,
    export_format="GLB",
    use_selection=True,
    export_apply=True,
    export_yup=True,
    export_materials="EXPORT",
    export_attributes=False,
    export_cameras=False,
    export_lights=False,
)

source_object_count = len(export_objects)
source_mesh_count = len(mesh_objects)
source_vertex_count = sum(len(obj.data.vertices) for obj in mesh_objects)
file_bytes = os.path.getsize(OUTPUT)

# Re-import the produced GLB into a clean scene and validate the actual deliverable.
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.gltf(filepath=OUTPUT)
imported = list(bpy.context.scene.objects)
imported_meshes = [obj for obj in imported if obj.type == "MESH"]
imported_roots = [obj for obj in imported if obj.name == "Ancient_Railway_Environment_ROOT"]
if len(imported_roots) != 1:
    raise RuntimeError(f"GLB re-import root validation failed: found {len(imported_roots)} named roots")
if any(obj.type in {"CAMERA", "LIGHT"} for obj in imported):
    raise RuntimeError("GLB re-import unexpectedly contains camera/light objects")
if not imported_meshes:
    raise RuntimeError("GLB re-import contains no meshes")

re_min, re_max = world_bounds(imported_meshes)
re_dimensions = re_max - re_min
# In glTF/Blender round-trip, exporter/importer restores Blender Z-up dimensions.
if abs(re_dimensions.y - dimensions.y) > 0.05:
    raise RuntimeError(f"GLB re-import dimension mismatch: {re_dimensions.y:.3f}m vs {dimensions.y:.3f}m")

print("ANCIENT_RAILWAY_EXPORT_OK")
print(f"Output: {OUTPUT}")
print(f"Dimensions XYZ (m): {dimensions.x:.3f} x {dimensions.y:.3f} x {dimensions.z:.3f}")
print(f"Bounds min XYZ (m): {minimum.x:.3f}, {minimum.y:.3f}, {minimum.z:.3f}")
print(f"Bounds max XYZ (m): {maximum.x:.3f}, {maximum.y:.3f}, {maximum.z:.3f}")
print(f"Source objects: {source_object_count} ({source_mesh_count} meshes)")
print(f"Source vertices: {source_vertex_count}")
print(f"File bytes: {file_bytes}")
print(f"Re-import objects: {len(imported)} ({len(imported_meshes)} meshes)")
print(f"Re-import dimensions XYZ (m): {re_dimensions.x:.3f} x {re_dimensions.y:.3f} x {re_dimensions.z:.3f}")
print("Re-import verification: PASS")


# ---------- independently wrapped distant skyline ----------
# Keep this asset deliberately broad, sparse, and fully outside the playable lane. It is
# exported separately so the runtime can wrap it at a slower background cadence.
SKYLINE_OUTPUT = os.path.join(ROOT, "public", "models", "environment", "ancient_skyline.glb")
SKYLINE_CLEAR_HALF_WIDTH = 14.0

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
for collection in (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
    for datablock in list(collection):
        collection.remove(datablock)

scene = bpy.context.scene
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 1.0
scene.render.engine = "BLENDER_EEVEE"

SKY_STONE = material("Skyline Blue Stone", "53676C", 0.94)
SKY_ROOF = material("Skyline Deep Teal Roof", "24575B", 0.88)
SKY_FOLIAGE = material("Skyline Pine Mass", "385B4E", 0.96)
SKY_MOUNTAIN_MID = material("Skyline Mountain Mid", "6E8584", 1.0)
SKY_MOUNTAIN_FAR = material("Skyline Mountain Far", "91A19C", 1.0)

skyline_root = empty("Ancient_Skyline_ROOT")
skyline_root["asset_type"] = "visual_only_wrapped_distant_background"
skyline_root["metric_length_m"] = 96.0
skyline_root["playable_clear_half_width_m"] = SKYLINE_CLEAR_HALF_WIDTH
skyline_root["coordinate_note"] = "Authored Blender Z-up; exported glTF Y-up"
skyline_root["placement_note"] = "Distant side scenery; independently wrap along the run axis"
skyline_root["collision_note"] = "Visual background only; no gameplay collision metadata"

skyline_parts = []


def skyline_mesh(name, vertices, faces, mat):
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    apply_material(obj, mat)
    skyline_parts.append(obj)
    return obj


def skyline_cube(name, location, dimensions, mat, rotation=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(location=location, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    apply_material(obj, mat)
    skyline_parts.append(obj)
    return obj


def skyline_roof(name, location, width, length, height):
    """Simple hipped roof; silhouette matters more than close-range construction detail."""
    x, y, z = location
    inset = min(width * 0.22, length * 0.20)
    vertices = [
        (x - width / 2, y - length / 2, z), (x + width / 2, y - length / 2, z),
        (x + width / 2, y + length / 2, z), (x - width / 2, y + length / 2, z),
        (x - width / 2 + inset, y - length / 2 + inset, z + height),
        (x + width / 2 - inset, y - length / 2 + inset, z + height),
        (x + width / 2 - inset, y + length / 2 - inset, z + height),
        (x - width / 2 + inset, y + length / 2 - inset, z + height),
    ]
    faces = [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7), (4, 5, 6, 7), (0, 3, 2, 1)]
    skyline_mesh(name, vertices, faces, SKY_ROOF)


def mountain_ridge(name, side, x_near, thickness, heights, mat):
    """Extruded faceted ridge running along Y, kept on one side of the corridor."""
    y_step = 96.0 / (len(heights) - 1)
    y_values = [-48.0 + index * y_step for index in range(len(heights))]
    x_inner = side * x_near
    x_outer = side * (x_near + thickness)
    vertices = []
    for x in (x_inner, x_outer):
        vertices.extend((x, y, 0.0) for y in y_values)
        vertices.extend((x, y, height) for y, height in zip(y_values, heights))
    count = len(heights)
    inner_bottom = 0
    inner_top = count
    outer_bottom = count * 2
    outer_top = count * 3
    faces = []
    for index in range(count - 1):
        # Visible inner face, outer face, ridge top, and floor close the low-poly slab.
        faces.append((inner_bottom + index, inner_bottom + index + 1, inner_top + index + 1, inner_top + index))
        faces.append((outer_bottom + index + 1, outer_bottom + index, outer_top + index, outer_top + index + 1))
        faces.append((inner_top + index, inner_top + index + 1, outer_top + index + 1, outer_top + index))
        faces.append((inner_bottom + index + 1, inner_bottom + index, outer_bottom + index, outer_bottom + index + 1))
    faces.extend([
        (inner_bottom, inner_top, outer_top, outer_bottom),
        (inner_bottom + count - 1, outer_bottom + count - 1, outer_top + count - 1, inner_top + count - 1),
    ])
    skyline_mesh(name, vertices, faces, mat)


def watchtower(name, side, y, scale=1.0):
    x = side * 23.5
    skyline_cube(name + "_Base", (x, y, 4.0 * scale), (4.0 * scale, 6.0 * scale, 8.0 * scale), SKY_STONE)
    skyline_roof(name + "_Roof", (x, y, 8.0 * scale), 5.4 * scale, 7.3 * scale, 1.65 * scale)
    skyline_cube(name + "_Crown", (x, y, 9.75 * scale), (2.2 * scale, 3.6 * scale, 1.8 * scale), SKY_STONE)
    skyline_roof(name + "_CrownRoof", (x, y, 10.65 * scale), 3.5 * scale, 4.8 * scale, 1.15 * scale)


def pagoda(name, side, y):
    x = side * 31.0
    skyline_cube(name + "_Podium", (x, y, 1.2), (7.0, 8.0, 2.4), SKY_STONE)
    levels = ((2.4, 6.0, 7.0), (6.6, 4.8, 5.7), (10.1, 3.7, 4.5), (13.0, 2.7, 3.5))
    for index, (z, width, length) in enumerate(levels, 1):
        skyline_cube(f"{name}_Level_{index}", (x, y, z + 1.25), (width, length, 2.5), SKY_STONE)
        skyline_roof(f"{name}_Roof_{index}", (x, y, z + 2.5), width + 2.1, length + 2.3, 1.4)
    skyline_cube(name + "_Finial", (x, y, 17.6), (0.32, 0.32, 2.4), SKY_ROOF)


# Two muted mountain planes provide depth without requiring transparency or dense geometry.
for side, label in ((-1, "Left"), (1, "Right")):
    mountain_ridge(
        label + "_Far_Mountains", side, 56.0, 18.0,
        (8.0, 13.0, 10.5, 18.0, 12.0, 21.0, 11.5, 16.5, 9.0), SKY_MOUNTAIN_FAR,
    )
    mountain_ridge(
        label + "_Mid_Mountains", side, 40.0, 12.0,
        (5.0, 11.5, 7.5, 15.0, 8.0, 17.0, 9.5, 13.0, 6.5), SKY_MOUNTAIN_MID,
    )

# Continuous walls and roofline blocks read as a city silhouette over a full wrap interval.
for side, label in ((-1, "Left"), (1, "Right")):
    skyline_cube(label + "_City_Wall", (side * 22.0, 0, 2.2), (3.0, 96.0, 4.4), SKY_STONE)
    for index, y in enumerate(range(-44, 45, 8)):
        skyline_cube(f"{label}_Wall_Merlon_{index + 1}", (side * 20.35, y, 4.85), (0.70, 3.5, 0.90), SKY_STONE)
    for index, (y, length, height, setback) in enumerate(((-36, 10, 5.5, 4.0), (-23, 9, 7.0, 5.5), (-8, 12, 5.0, 3.5), (10, 11, 6.5, 5.0), (25, 9, 5.0, 4.0), (39, 10, 6.0, 5.5))):
        x = side * (23.5 + setback)
        skyline_cube(f"{label}_Roofline_Block_{index + 1}", (x, y, 2.2 + height / 2), (4.0, length, height), SKY_STONE)
        skyline_roof(f"{label}_Roofline_Roof_{index + 1}", (x, y, 2.2 + height), 5.2, length + 1.4, 1.25)
    for tower_index, y in enumerate((-31.0, 0.0, 32.0), 1):
        watchtower(f"{label}_Watchtower_{tower_index}", side, y, 0.92 if tower_index != 2 else 1.0)

# One dominant pagoda and a lower counterpoint make the skyline asymmetric and recognizable.
pagoda("Left_Landmark_Pagoda", -1, 16.0)
pagoda("Right_Distant_Pagoda", 1, -25.0)

# Low-poly tree masses break up the wall base. Icospheres are consolidated by material below.
for side, label in ((-1, "Left"), (1, "Right")):
    for index, (y, radius, x_offset) in enumerate(((-42, 2.7, 0.0), (-28, 3.3, 2.0), (-15, 2.5, 0.8), (5, 3.5, 2.5), (20, 2.8, 0.4), (35, 3.4, 2.1), (45, 2.4, 0.5))):
        x = side * (25.5 + x_offset)
        skyline_cube(f"{label}_Tree_Trunk_{index + 1}", (x, y, 2.0), (0.7, 0.7, 4.0), SKY_STONE)
        for crown_index, (dy, dz, size) in enumerate(((-1.1, 4.2, 1.0), (0.9, 4.6, 0.9), (0.0, 6.0, 1.1)), 1):
            bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=radius * size, location=(x, y + dy, dz))
            crown = bpy.context.object
            crown.name = f"{label}_Tree_Crown_{index + 1}_{crown_index}"
            crown.scale = (0.80, 1.0, 0.86)
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            apply_material(crown, SKY_FOLIAGE)
            skyline_parts.append(crown)

# Consolidate all pieces sharing a material. The delivered asset stays at five meshes even
# though its silhouette contains many landmarks and repeated city details.
for mat in (SKY_STONE, SKY_ROOF, SKY_FOLIAGE, SKY_MOUNTAIN_MID, SKY_MOUNTAIN_FAR):
    material_parts = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.data.materials and obj.data.materials[0] == mat]
    bpy.ops.object.select_all(action="DESELECT")
    for obj in material_parts:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = material_parts[0]
    bpy.ops.object.join()
    joined = bpy.context.object
    joined.name = mat.name.replace(" ", "_")
    set_parent_keep_world(joined, skyline_root)

skyline_export_objects = [skyline_root, *skyline_root.children_recursive]
skyline_meshes = [obj for obj in skyline_export_objects if obj.type == "MESH"]
skyline_violations = []
for obj in skyline_meshes:
    for vertex in obj.data.vertices:
        point = obj.matrix_world @ vertex.co
        if -SKYLINE_CLEAR_HALF_WIDTH < point.x < SKYLINE_CLEAR_HALF_WIDTH:
            skyline_violations.append((obj.name, point.x))
            break
if skyline_violations:
    raise RuntimeError(f"Distant skyline corridor violation(s): {skyline_violations}")
if len(skyline_meshes) > 6 or len(bpy.data.materials) > 6:
    raise RuntimeError(f"Distant skyline must remain lightweight, got {len(skyline_meshes)} meshes and {len(bpy.data.materials)} materials")
if bpy.data.cameras or bpy.data.lights:
    raise RuntimeError("Distant skyline export must not contain cameras or lights")

skyline_minimum, skyline_maximum = world_bounds(skyline_meshes)
skyline_dimensions = skyline_maximum - skyline_minimum
if not (90.0 <= skyline_dimensions.y <= 100.0):
    raise RuntimeError(f"Skyline wrap length must be 90-100m, got {skyline_dimensions.y:.3f}m")

bpy.ops.object.select_all(action="DESELECT")
for obj in skyline_export_objects:
    obj.select_set(True)
bpy.context.view_layer.objects.active = skyline_root
os.makedirs(os.path.dirname(SKYLINE_OUTPUT), exist_ok=True)
bpy.ops.export_scene.gltf(
    filepath=SKYLINE_OUTPUT,
    export_format="GLB",
    use_selection=True,
    export_apply=True,
    export_yup=True,
    export_materials="EXPORT",
    export_attributes=False,
    export_cameras=False,
    export_lights=False,
)

skyline_source_object_count = len(skyline_export_objects)
skyline_source_mesh_count = len(skyline_meshes)
skyline_source_vertex_count = sum(len(obj.data.vertices) for obj in skyline_meshes)
skyline_source_triangle_count = sum(len(obj.data.loop_triangles) for obj in skyline_meshes)
skyline_material_count = len({slot.material.name for obj in skyline_meshes for slot in obj.material_slots})
skyline_file_bytes = os.path.getsize(SKYLINE_OUTPUT)

# Clean re-import validation verifies the standalone deliverable, not just the authoring scene.
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.gltf(filepath=SKYLINE_OUTPUT)
skyline_imported = list(bpy.context.scene.objects)
skyline_imported_meshes = [obj for obj in skyline_imported if obj.type == "MESH"]
skyline_imported_roots = [obj for obj in skyline_imported if obj.name == "Ancient_Skyline_ROOT"]
if len(skyline_imported_roots) != 1:
    raise RuntimeError(f"Skyline GLB re-import root validation failed: found {len(skyline_imported_roots)} named roots")
if any(obj.type in {"CAMERA", "LIGHT"} for obj in skyline_imported):
    raise RuntimeError("Skyline GLB re-import unexpectedly contains camera/light objects")
if len(skyline_imported_meshes) != skyline_source_mesh_count:
    raise RuntimeError(f"Skyline GLB re-import mesh mismatch: {len(skyline_imported_meshes)} vs {skyline_source_mesh_count}")

skyline_re_min, skyline_re_max = world_bounds(skyline_imported_meshes)
skyline_re_dimensions = skyline_re_max - skyline_re_min
if any(abs(a - b) > 0.05 for a, b in zip(skyline_re_dimensions, skyline_dimensions)):
    raise RuntimeError(f"Skyline GLB re-import dimension mismatch: {tuple(skyline_re_dimensions)} vs {tuple(skyline_dimensions)}")

print("ANCIENT_SKYLINE_EXPORT_OK")
print(f"Output: {SKYLINE_OUTPUT}")
print(f"Dimensions XYZ (m): {skyline_dimensions.x:.3f} x {skyline_dimensions.y:.3f} x {skyline_dimensions.z:.3f}")
print(f"Bounds min XYZ (m): {skyline_minimum.x:.3f}, {skyline_minimum.y:.3f}, {skyline_minimum.z:.3f}")
print(f"Bounds max XYZ (m): {skyline_maximum.x:.3f}, {skyline_maximum.y:.3f}, {skyline_maximum.z:.3f}")
print(f"Source objects: {skyline_source_object_count} ({skyline_source_mesh_count} meshes)")
print(f"Source vertices: {skyline_source_vertex_count}")
print(f"Source triangles: {skyline_source_triangle_count}")
print(f"Materials: {skyline_material_count}")
print(f"File bytes: {skyline_file_bytes}")
print(f"Re-import objects: {len(skyline_imported)} ({len(skyline_imported_meshes)} meshes)")
print(f"Re-import dimensions XYZ (m): {skyline_re_dimensions.x:.3f} x {skyline_re_dimensions.y:.3f} x {skyline_re_dimensions.z:.3f}")
print("Skyline re-import verification: PASS")
