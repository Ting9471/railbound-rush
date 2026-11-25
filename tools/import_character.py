#!/usr/bin/env python3
"""Reproducible FBX -> normalized, skinned GLB character pipeline.

Run with Blender --background --factory-startup --python tools/import_character.py
-- --input character.fbx --output-dir staging/ch09 [--skip-render].
Also usable with system Python; it launches the installed Blender executable.
Only the output directory is written. Source geometry, UVs and skin bones survive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--skip-render', action='store_true')
    parser.add_argument('--source-reference-only', action='store_true',
                        help='Render untouched blend diffuse surfaces at normalized camera scale, without exporting.')
    parser.add_argument('--texture-size', type=int, default=None,
                        help='Maximum export texture edge; omitted keeps source resolution. Blend stays full resolution.')
    parser.add_argument('--clip-override', action='append', default=[], metavar='CLIP=FBX',
                        help='Replace one gameplay clip using animation from a matching FBX rig; repeatable.')
    parser.add_argument('--height', type=float, default=1.82)
    parser.add_argument('--blender', default='/Applications/Blender.app/Contents/MacOS/Blender')
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    return parser.parse_args(argv)


try:
    import bpy
    from mathutils import Matrix, Quaternion, Vector
except ImportError:
    if __name__ == '__main__':
        args = arguments()
        executable = shutil.which(args.blender) or args.blender
        raise SystemExit(subprocess.call([executable, '--disable-autoexec', '--background', '--factory-startup', '--python-exit-code', '1',
                                         '--python', str(Path(__file__).resolve()), '--', *sys.argv[1:]]))
    raise


def bounds(meshes):
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    low = [math.inf] * 3
    high = [-math.inf] * 3
    finite = True
    count = 0
    for obj in meshes:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            for vertex in mesh.vertices:
                co = evaluated.matrix_world @ vertex.co
                finite = finite and all(math.isfinite(v) for v in co)
                for i in range(3):
                    low[i] = min(low[i], co[i])
                    high[i] = max(high[i], co[i])
                count += 1
        finally:
            evaluated.to_mesh_clear()
    if not count:
        raise RuntimeError('No mesh vertices')
    return {'min': low, 'max': high, 'dimensions': [high[i] - low[i] for i in range(3)],
            'finite': finite}


def curves(action):
    if hasattr(action, 'layers'):
        return [fc for layer in action.layers for strip in layer.strips
                for bag in strip.channelbags for fc in bag.fcurves]
    return list(action.fcurves)


def action_is_moving(action):
    return any(len(fc.keyframe_points) > 1 and
               max(k.co.y for k in fc.keyframe_points) - min(k.co.y for k in fc.keyframe_points) > 1e-5
               for fc in curves(action))


def set_action(armature, action):
    armature.animation_data_create()
    armature.animation_data.action = action
    if action and action.slots:
        armature.animation_data.action_slot = action.slots[0]


def reset_pose(armature):
    for bone in armature.pose.bones:
        bone.rotation_mode = 'QUATERNION'
        bone.matrix_basis = Matrix.Identity(4)


def inspect(armature, meshes):
    return {
        'mesh_objects': [{'name': obj.name, 'vertices': len(obj.data.vertices),
                          'polygons': len(obj.data.polygons), 'loops': len(obj.data.loops),
                          'uv_layers': [uv.name for uv in obj.data.uv_layers],
                          'materials': [slot.material.name if slot.material else None for slot in obj.material_slots],
                          'vertex_groups': len(obj.vertex_groups),
                          'modifiers': [{'type': m.type, 'name': m.name} for m in obj.modifiers]}
                         for obj in meshes],
        'bones': [{'name': b.name, 'parent': b.parent.name if b.parent else None,
                   'head_world': list(armature.matrix_world @ b.head_local),
                   'tail_world': list(armature.matrix_world @ b.tail_local), 'deform': b.use_deform}
                  for b in armature.data.bones],
        'actions': [{'name': a.name, 'frames': list(a.frame_range), 'moving': action_is_moving(a),
                     'channel_count': len(curves(a))} for a in bpy.data.actions],
        'images': [{'name': image.name, 'original_path': image.filepath,
                    'size': list(image.size), 'embedded': bool(image.packed_file),
                    'has_pixels': image.has_data}
                   for image in bpy.data.images if image.source != 'VIEWER'],
        'materials': [{'name': mat.name,
                       'links': [{'from': link.from_node.name, 'output': link.from_socket.name,
                                  'to': link.to_node.name, 'input': link.to_socket.name}
                                 for link in mat.node_tree.links] if mat.node_tree else []}
                      for mat in {slot.material for obj in meshes for slot in obj.material_slots if slot.material}],
        'imported_pose_bounds': bounds(meshes),
    }


def bone_lookup(armature):
    return {b.name.split(':')[-1]: b for b in armature.data.bones}


def extract_materials(meshes, directory):
    """Keep diffuse/normal pixels; convert non-PBR gloss to linear roughness."""
    import numpy as np
    directory.mkdir(parents=True, exist_ok=True)
    materials = {s.material for o in meshes for s in o.material_slots if s.material}
    images = {n.image for m in materials if m.node_tree for n in m.node_tree.nodes
              if n.type == 'TEX_IMAGE' and n.image}
    missing = []
    records = []
    for image in sorted(images, key=lambda i: i.name):
        original_path = image.filepath
        if not image.has_data or min(image.size) == 0:
            missing.append(original_path or image.name)
            continue
        filename = re.split(r'[/\\]', original_path)[-1] or image.name + '.png'
        path = directory / filename
        if image.packed_file:
            path.write_bytes(bytes(image.packed_file.data))
            image.unpack(method='REMOVE')
        else:
            source = Path(bpy.path.abspath(original_path))
            if not source.is_file():
                missing.append(original_path)
                continue
            shutil.copyfile(source, path)
        image.filepath = str(path)
        records.append({'name': image.name, 'file': str(path), 'size': list(image.size),
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    conversions = []
    for mat in materials:
        mat.use_nodes = True
        tree = mat.node_tree
        shader = next((n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if not shader:
            raise RuntimeError(f'Unsupported surface material: {mat.name}')
        shader.inputs['Metallic'].default_value = 0.0
        shader.inputs['Specular IOR Level'].default_value = 0.25
        rough_link = next(iter(shader.inputs['Roughness'].links), None)
        if rough_link and rough_link.from_node.type == 'TEX_IMAGE':
            gloss = rough_link.from_node.image
            if gloss and 'gloss' in (gloss.filepath + gloss.name).lower() and gloss.has_data:
                # Gloss is non-color data. No recoloring, channel inversion only.
                gloss.colorspace_settings.name = 'Non-Color'
                width, height = gloss.size
                pixels = np.empty(width * height * 4, dtype=np.float32)
                gloss.pixels.foreach_get(pixels)
                pixels = pixels.reshape((-1, 4))
                pixels[:, :3] = np.clip(1.0 - pixels[:, :3], 0.35, 0.95)
                pixels[:, 3] = 1.0
                rough = bpy.data.images.new('Ch09_Roughness_from_Glossiness', width, height, alpha=True)
                rough.colorspace_settings.name = 'Non-Color'
                rough.pixels.foreach_set(pixels.ravel())
                rough.filepath_raw = str(directory / 'roughness_from_glossiness.png')
                rough.file_format = 'PNG'
                rough.save()
                rough.pack()
                rough_link.from_node.image = rough
                conversions.append({'material': mat.name, 'roughness': 'clamp(1 - glossiness, 0.35, 0.95)',
                                    'range': [float(pixels[:, 0].min()), float(pixels[:, 0].max())]})
        else:
            shader.inputs['Roughness'].default_value = 0.72
        # Non-PBR specular is preserved, but must not drive a dielectric to white plastic.
        for link in list(shader.inputs['Specular IOR Level'].links):
            tree.links.remove(link)
        for node in tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image:
                role = (node.image.filepath + node.image.name).lower()
                if 'diffuse' in role:
                    node.image.colorspace_settings.name = 'sRGB'
                elif any(term in role for term in ('normal', 'specular', 'gloss', 'roughness')):
                    node.image.colorspace_settings.name = 'Non-Color'
        for image in images:
            if image.has_data and not image.packed_file:
                image.pack()
    return {'extracted': records, 'missing': missing, 'conversions': conversions,
            'specular_policy': 'Nonmetal dielectric specular IOR level 0.25; source specular retained in textures/blend'}


def resize_export_images(meshes, directory, maximum):
    """Resize independent image copies AFTER saving the full-resolution blend.

    Only images reachable from the material output are replaced. Packed source
    bytes must be removed from copies, otherwise glTF may reuse the original PNG.
    Geometry, UVs, bones, weights and animation are not touched.
    """
    if maximum is None:
        return []
    directory.mkdir(parents=True, exist_ok=True)
    replacements = {}
    records = []
    materials = {s.material for obj in meshes for s in obj.material_slots if s.material}
    for material in materials:
        tree = material.node_tree
        pending = [n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output]
        visited = set()
        while pending:
            node = pending.pop()
            if node in visited:
                continue
            visited.add(node)
            pending.extend(link.from_node for socket in node.inputs for link in socket.links)
            if node.type != 'TEX_IMAGE' or not node.image:
                continue
            original = node.image
            if original not in replacements:
                old_size = list(original.size)  # Querying size resolves Blender's lazy image buffer.
                if min(old_size) == 0:
                    original.reload()
                    old_size = list(original.size)
                if min(old_size) == 0:
                    raise RuntimeError(f'Cannot resize missing texture {original.name}')
                ratio = min(1.0, maximum / max(old_size))
                new_size = [max(1, round(edge * ratio)) for edge in old_size]
                image = original.copy()
                image.name = original.name + f'_export_{maximum}'
                if image.packed_file:
                    image.unpack(method='REMOVE')
                image.reload()
                image.scale(*new_size)
                image.filepath_raw = str(directory / (image.name + '.png'))
                image.file_format = 'PNG'
                image.save()
                image.pack()
                replacements[original] = image
                records.append({'source_image': original.name, 'source_size': old_size,
                                'export_image': image.name, 'export_size': new_size,
                                'file': image.filepath, 'format': 'PNG'})
            node.image = replacements[original]
    return records


def capture_original(armature, actions, scene):
    captures = []
    for action in actions:
        set_action(armature, action)
        start, end = map(int, action.frame_range)
        samples = []
        for frame in range(start, end + 1):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            samples.append((frame, {p.name: armature.matrix_world @ p.matrix for p in armature.pose.bones}))
        captures.append((action.name, start, end, samples))
    return captures


def capture_clip_override(armature, spec, output):
    """Import motion only. Reject different bind rigs instead of deforming the model."""
    kind, separator, filename = spec.partition('=')
    if not separator or kind not in ('Idle', 'Run', 'Jump', 'Slide'):
        raise RuntimeError('Clip override must be Idle/Run/Jump/Slide=/path/to/motion.fbx')
    source = Path(filename).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != '.fbx':
        raise RuntimeError(f'Animation source must be an existing FBX: {source}')
    if source.is_relative_to(output):
        raise RuntimeError('Output must not contain the original animation source')
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    scene = bpy.context.scene
    target_fps, target_fps_base = scene.render.fps, scene.render.fps_base
    data_names = ('objects', 'actions', 'meshes', 'armatures', 'materials', 'images', 'cameras', 'lights', 'collections')
    before_data = {name: set(getattr(bpy.data, name)) for name in data_names}
    before_objects, before_actions = before_data['objects'], before_data['actions']
    try:
        bpy.ops.import_scene.fbx(filepath=str(source), use_anim=True)
        imported_objects = set(bpy.data.objects) - before_objects
        rigs = [obj for obj in imported_objects if obj.type == 'ARMATURE']
        if len(rigs) != 1:
            raise RuntimeError(f'Animation FBX must have one rig, found {len(rigs)}')
        motion = rigs[0]
        target_bones, motion_bones = bone_lookup(armature), bone_lookup(motion)
        if len(target_bones) != len(armature.data.bones) or len(motion_bones) != len(motion.data.bones):
            raise RuntimeError('Ambiguous bone suffixes in animation rig')
        if set(target_bones) != set(motion_bones):
            raise RuntimeError('Animation and character rigs have different bones')
        worst_bind_error = 0.0
        for name, target in target_bones.items():
            bone = motion_bones[name]
            parent_name = lambda b: b.parent.name.split(':')[-1] if b.parent else None
            if parent_name(target) != parent_name(bone):
                raise RuntimeError(f'Animation bone hierarchy mismatch: {name}')
            target_bind = armature.matrix_world @ target.matrix_local
            motion_bind = motion.matrix_world @ bone.matrix_local
            worst_bind_error = max(worst_bind_error,
                max(abs(target_bind[r][c] - motion_bind[r][c]) for r in range(4) for c in range(4)))
        if worst_bind_error > 0.0001:
            raise RuntimeError(f'Animation bind pose differs from character: {worst_bind_error}')
        actions = [a for a in bpy.data.actions if a not in before_actions and action_is_moving(a)]
        if len(actions) != 1:
            raise RuntimeError(f'Expected exactly one moving FBX action, found {len(actions)}')
        set_action(motion, actions[0])
        source_start, source_end = actions[0].frame_range
        source_rate = scene.render.fps / scene.render.fps_base
        target_rate = target_fps / target_fps_base
        duration = (source_end - source_start) / source_rate
        start, end = 1, max(1, round(duration * target_rate)) + 1
        name_map = {bone.name: target_bones[name].name for name, bone in motion_bones.items()}
        remapped = []
        for frame in range(start, end + 1):
            source_frame = source_start + (source_end - source_start) * (frame - start) / (end - start)
            scene.frame_set(math.floor(source_frame), subframe=source_frame % 1)
            bpy.context.view_layer.update()
            remapped.append((frame, {name_map[p.name]: motion.matrix_world @ p.matrix
                                     for p in motion.pose.bones}))
        if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
            raise RuntimeError('Animation source changed during import')
        return (kind, start, end, remapped), {
            'name': kind, 'source': str(source), 'source_sha256': source_hash,
            'source_unchanged': True, 'source_action': actions[0].name,
            'frames': [start, end], 'source_frames': [source_start, source_end],
            'source_fps': source_rate, 'export_fps': target_rate,
            'bones_matched': len(name_map), 'max_bind_error': worst_bind_error}
    finally:
        scene.render.fps, scene.render.fps_base = target_fps, target_fps_base
        for name in data_names:
            collection = getattr(bpy.data, name)
            for block in set(collection) - before_data[name]:
                collection.remove(block, do_unlink=True)


def normalize(armature, meshes, target_height):
    armature.animation_data_clear()
    reset_pose(armature)
    armature.data.pose_position = 'REST'
    source_bounds = bounds(meshes)
    lookup = bone_lookup(armature)
    required = ('LeftFoot', 'LeftToeBase', 'RightFoot', 'RightToeBase')
    if not all(key in lookup for key in required):
        raise RuntimeError('Cannot infer facing reliably: feet/toe bone pairs missing')
    forward = sum((armature.matrix_world @ lookup[s + 'ToeBase'].head_local -
                   armature.matrix_world @ lookup[s + 'Foot'].head_local for s in ('Left', 'Right')), Vector())
    forward.z = 0
    if forward.length < 1e-6:
        raise RuntimeError('Degenerate toe direction')
    forward.normalize()
    yaw = -math.pi / 2 - math.atan2(forward.y, forward.x)
    rotation = Matrix.Rotation(yaw, 4, 'Z')
    scale = target_height / source_bounds['dimensions'][2]
    transform = Matrix.Scale(scale, 4) @ rotation
    rotated_points = [transform @ obj.matrix_world @ v.co for obj in meshes for v in obj.data.vertices]
    low = Vector([min(v[i] for v in rotated_points) for i in range(3)])
    high = Vector([max(v[i] for v in rotated_points) for i in range(3)])
    offset = Vector((-(low.x + high.x) / 2, -(low.y + high.y) / 2, -low.z))
    transform = Matrix.Translation(offset) @ transform
    objects = [armature, *meshes]
    worlds = {obj: obj.matrix_world.copy() for obj in objects}
    for obj in objects:
        obj.parent = None
        if obj.type == 'MESH' and obj.data.shape_keys:
            obj.data.transform(transform @ worlds[obj], shape_keys=True)
        else:
            obj.data.transform(transform @ worlds[obj])
        obj.matrix_world = Matrix.Identity(4)
    for obj in meshes:
        obj.data.update()
        obj.parent = armature
        obj.matrix_parent_inverse = Matrix.Identity(4)
    armature.data.pose_position = 'POSE'
    reset_pose(armature)
    return transform, {'source_rest_bounds': source_bounds, 'source_facing_vector': list(forward),
                       'yaw_radians': yaw, 'scale_baked': scale, 'offset_baked': list(offset),
                       'authored_up': '+Z', 'authored_forward': '-Y',
                       'glb_up': '+Y', 'glb_forward': '+Z', 'three_scale': 1.0,
                       'rest_bounds': bounds(meshes), 'geometry_and_rig_baked_together': True}


def qx(degrees):
    return Quaternion((1, 0, 0), math.radians(degrees))


def directed(bone, direction):
    return (bone.tail_local - bone.head_local).normalized().rotation_difference(Vector(direction).normalized())


def pose_deltas(armature, deltas, hip_offset):
    """Convert absolute armature-space rotation deltas through each bone's rest basis.

    Qbasis = Rrest^-1 * Dparent^-1 * Dbone * Rrest. This handles FBX/Mixamo
    arbitrary rolls, not legacy pivot Euler values, and keeps all finger bones.
    """
    applied = {}
    for bone in armature.data.bones:
        delta = deltas.get(bone.name, applied.get(bone.parent.name, Quaternion()) if bone.parent else Quaternion())
        parent_delta = applied.get(bone.parent.name, Quaternion()) if bone.parent else Quaternion()
        rest = bone.matrix_local.to_quaternion()
        pb = armature.pose.bones[bone.name]
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = rest.inverted() @ parent_delta.inverted() @ delta @ rest
        pb.location = (0, 0, 0)
        pb.scale = (1, 1, 1)
        if bone.name.split(':')[-1] == 'Hips':
            pb.location = rest.inverted() @ Vector(hip_offset)
        applied[bone.name] = delta


def generated_pose(kind, t, lookup):
    deltas = {}
    def put(name, q):
        if name in lookup:
            deltas[lookup[name].name] = q
    wave = math.sin(2 * math.pi * t)
    lean = 8 if kind == 'Run' else 0
    if kind == 'Jump':
        lean = 7 * math.sin(math.pi * t) ** 2
    if kind == 'Slide':
        lean = -64 + 2 * wave
    body = qx(lean)
    put('Hips', body)
    put('Spine', qx(lean * 0.85))
    put('Spine1', qx(lean * 0.75))
    put('Spine2', qx(lean * 0.65))
    put('Neck', qx(lean * 0.3))
    put('Head', qx(lean * 0.15))
    if kind == 'Slide':
        # The source has an oversized head: the entire torso/head must recline,
        # not just the hips, to satisfy a genuine low silhouette without scaling.
        for name in ('Spine', 'Spine1', 'Spine2', 'Neck', 'Head'):
            put(name, qx(-94 + wave))
    for side, sign in [('Left', 1), ('Right', -1)]:
        phase = wave * sign
        if kind == 'Run':
            thigh = -42 * phase
            shin = thigh + 12 + 78 * max(0, phase)
            swing = -phase * 0.62
            arm_direction = (sign * 0.12, swing, -0.9)
            fore_direction = (sign * 0.07, -0.88 + swing * 0.2, 0.30)
            foot_angle = max(0, phase) * 16
        elif kind == 'Slide':
            thigh, shin, foot_angle = -88 + sign * 2, -100 + sign * 2, -10
            arm_direction = (sign * 0.22, -0.95, -0.08)
            fore_direction = (sign * 0.16, -0.95, 0.08)
        elif kind == 'Jump':
            tuck = math.sin(math.pi * t) ** 2
            thigh = -30 * tuck + sign * 8 * tuck
            shin = thigh + 65 * tuck
            foot_angle = 12 * tuck
            arm_direction = (sign * 0.15, -0.22 - tuck * 0.6, -0.8 + tuck * 0.35)
            fore_direction = (sign * 0.07, -0.7, 0.15 + 0.6 * tuck)
        else:
            thigh, shin, foot_angle = 0, 2, 0
            arm_direction = (sign * 0.13, 0.03 + wave * 0.025, -0.99)
            fore_direction = (sign * 0.07, -0.2, -0.98)
        put(side + 'UpLeg', qx(thigh))
        put(side + 'Leg', qx(shin))
        put(side + 'Foot', qx(foot_angle))
        # Shoulders follow torso; arms have their own absolute direction targets.
        put(side + 'Arm', directed(lookup[side + 'Arm'], arm_direction))
        put(side + 'ForeArm', directed(lookup[side + 'ForeArm'], fore_direction))
        put(side + 'Hand', directed(lookup[side + 'ForeArm'], fore_direction))
    return deltas


def key_pose(armature, frame):
    for pb in armature.pose.bones:
        pb.keyframe_insert('rotation_quaternion', frame=frame, group=pb.name)
        if pb.name.split(':')[-1] == 'Hips':
            pb.keyframe_insert('location', frame=frame, group=pb.name)


def make_clips(armature, meshes, captures, transform):
    scene = bpy.context.scene
    lookup = bone_lookup(armature)
    generated = []
    reports = []
    # Preserve genuinely moving source animation using evaluated world matrices.
    for name, start, end, samples in captures:
        semantic = next((kind for kind in ('Idle', 'Run', 'Jump', 'Slide') if kind.lower() in name.lower()), None)
        if semantic and bpy.data.actions.get(semantic):
            bpy.data.actions[semantic].name = 'Source_' + semantic
        action = bpy.data.actions.new(semantic or name + '_Normalized')
        set_action(armature, action)
        reset_pose(armature)
        root = lookup['Hips']
        initial = transform @ samples[0][1][root.name]
        for frame, matrices in samples:
            scene.frame_set(frame)
            transformed = {}
            for n, matrix in matrices.items():
                world = transform @ matrix
                transformed[n] = Matrix.LocRotScale(world.translation, world.to_quaternion(), Vector((1, 1, 1)))
            shift = transformed[root.name].translation - initial.translation
            shift.z = 0
            for b in armature.data.bones:
                desired = transformed[b.name].copy()
                desired.translation -= shift
                parent = transformed[b.parent.name].copy() if b.parent else Matrix.Identity(4)
                if b.parent:
                    parent.translation -= shift
                pb = armature.pose.bones[b.name]
                pb.matrix_basis = b.convert_local_to_pose(desired, b.matrix_local,
                    parent_matrix=parent, parent_matrix_local=b.parent.matrix_local if b.parent else Matrix.Identity(4),
                    invert=True)
            correction = -bounds(meshes)['min'][2]
            hips = armature.pose.bones[root.name]
            hips.location += root.matrix_local.to_quaternion().inverted() @ Vector((0, 0, correction))
            for pb in armature.pose.bones:
                pb.keyframe_insert('rotation_quaternion', frame=frame)
                pb.keyframe_insert('location', frame=frame)
            key_pose(armature, frame)
        generated.append(action)
        reports.append({'name': action.name, 'origin': 'existing_source_animation_retargeted_in_place',
                        'start': start, 'end': end, 'duration': (end - start) / scene.render.fps})
    required = ('Hips', 'LeftArm', 'RightArm', 'LeftForeArm', 'RightForeArm',
                'LeftUpLeg', 'RightUpLeg', 'LeftLeg', 'RightLeg')
    if not all(k in lookup for k in required):
        if generated:
            return generated, reports
        raise RuntimeError('No moving animation and unsupported rig; no fabricated animations exported')
    # Generate only missing functional names, preserving source run/jump when present.
    for kind, seconds in [('Idle', 2.0), ('Run', 0.8), ('Jump', 0.9), ('Slide', 0.8)]:
        if any(kind.lower() in name.lower() for name, *_ in captures):
            continue
        action = bpy.data.actions.new(kind)
        set_action(armature, action)
        last = round(seconds * scene.render.fps)
        zmin, zmax = math.inf, -math.inf
        corrections = []
        for index in range(last + 1):
            frame = index + 1
            scene.frame_set(frame)
            reset_pose(armature)
            pose_deltas(armature, generated_pose(kind, index / last, lookup), (0, 0, 0))
            b = bounds(meshes)
            correction = -b['min'][2]
            hips = armature.pose.bones[lookup['Hips'].name]
            hips.location += lookup['Hips'].matrix_local.to_quaternion().inverted() @ Vector((0, 0, correction))
            b = bounds(meshes)
            if kind == 'Slide' and b['max'][2] > 0.90:
                raise RuntimeError(f'Slide pose exceeds limit at frame {frame}: {b}')
            zmin = min(zmin, b['min'][2])
            zmax = max(zmax, b['max'][2])
            corrections.append(correction)
            key_pose(armature, frame)
        for fc in curves(action):
            for key in fc.keyframe_points:
                key.interpolation = 'LINEAR'
        generated.append(action)
        reports.append({'name': kind, 'origin': 'local_procedural_existing_skin_bones',
                        'start': 1, 'end': last + 1, 'duration': last / scene.render.fps,
                        'minZ': zmin, 'maxZ': zmax, 'ground_correction_range': [min(corrections), max(corrections)],
                        'root_motion': False, 'object_scale': [1, 1, 1]})
    set_action(armature, None)
    reset_pose(armature)
    for action in generated:
        action.use_fake_user = True
        track = armature.animation_data.nla_tracks.new()
        track.name = action.name
        strip = track.strips.new(action.name, int(action.frame_range[0]), action)
        strip.extrapolation = 'NOTHING'
        track.mute = True
    return generated, reports


def glb_document(path):
    data = path.read_bytes()
    magic, version, length = struct.unpack_from('<4sII', data)
    if magic != b'glTF' or version != 2 or length != len(data):
        raise RuntimeError('Invalid GLB container')
    chunks = {}
    offset = 12
    while offset < len(data):
        size, kind = struct.unpack_from('<II', data, offset)
        chunks[kind] = data[offset + 8:offset + 8 + size]
        offset += size + 8
    return json.loads(chunks[0x4E4F534A]), chunks[0x004E4942]


def accessor_values(document, binary, index):
    accessor = document['accessors'][index]
    view = document['bufferViews'][accessor['bufferView']]
    widths = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}
    formats = {5120: 'b', 5121: 'B', 5122: 'h', 5123: 'H', 5125: 'I', 5126: 'f'}
    fmt = '<' + formats[accessor['componentType']] * widths[accessor['type']]
    stride = view.get('byteStride', struct.calcsize(fmt))
    offset = view.get('byteOffset', 0) + accessor.get('byteOffset', 0)
    return [struct.unpack_from(fmt, binary, offset + i * stride) for i in range(accessor['count'])]


def validate_glb(path, report, source_bone_count):
    document, binary = glb_document(path)
    image_records = []
    for image in document.get('images', []):
        view = document['bufferViews'][image['bufferView']]
        start = view.get('byteOffset', 0)
        payload = binary[start:start + view['byteLength']]
        if payload[:8] != b'\x89PNG\r\n\x1a\n':
            raise RuntimeError('Expected embedded PNG: no external texture decoder is configured')
        width, height = struct.unpack_from('>II', payload, 16)
        image_records.append({'name': image.get('name'), 'mimeType': image.get('mimeType'),
                              'size': [width, height], 'bytes': len(payload)})
    unsupported = set(document.get('extensionsRequired', [])) - {'KHR_materials_specular'}
    if unsupported:
        raise RuntimeError(f'Unexpected required loader extensions: {unsupported}')
    weight_sums = []
    geometry = []
    finite = all(math.isfinite(v) for index, accessor in enumerate(document['accessors'])
                 if 'bufferView' in accessor for row in accessor_values(document, binary, index) for v in row)
    joint_ranges_valid = True
    for mesh in document.get('meshes', []):
        for primitive in mesh['primitives']:
            attrs = primitive['attributes']
            if 'WEIGHTS_1' in attrs or 'JOINTS_1' in attrs:
                raise RuntimeError('Standard Three.js skinning requires only four influences')
            geometry.append({'mesh': mesh.get('name'),
                             'vertices': document['accessors'][attrs['POSITION']]['count'],
                             'triangles': document['accessors'][primitive['indices']]['count'] // 3,
                             'morph_targets': len(primitive.get('targets', []))})
            for key, index in attrs.items():
                finite = finite and all(math.isfinite(v) for row in accessor_values(document, binary, index) for v in row)
            weights = [accessor_values(document, binary, attrs[k]) for k in sorted(attrs) if k.startswith('WEIGHTS_')]
            if not weights:
                raise RuntimeError('GLB mesh lost skin weights')
            for index in range(len(weights[0])):
                weight_sums.append(sum(sum(group[index]) for group in weights))
            for key in attrs:
                if key.startswith('JOINTS_'):
                    joint_ranges_valid = joint_ranges_valid and all(0 <= j < source_bone_count
                        for row in accessor_values(document, binary, attrs[key]) for j in row)
    skins = document.get('skins', [])
    embedded = all('bufferView' in i for i in document.get('images', []))
    animations = []
    for anim in document.get('animations', []):
        times = [v[0] for sampler in anim['samplers']
                 for v in accessor_values(document, binary, sampler['input'])]
        for sampler in anim['samplers']:
            finite = finite and all(math.isfinite(v) for row in accessor_values(document, binary, sampler['output']) for v in row)
        animations.append({'name': anim['name'], 'duration': max(times) - min(times), 'channels': len(anim['channels'])})
    raw = {'finite_accessors': finite, 'weight_sum_range': [min(weight_sums), max(weight_sums)],
           'joint_indices_valid': joint_ranges_valid, 'skin_joint_counts': [len(s['joints']) for s in skins],
           'images_embedded': embedded, 'image_count': len(document.get('images', [])),
           'texture_count': len(document.get('textures', [])), 'animations': animations,
           'materials': document.get('materials', []), 'images': image_records,
           'extensions_used': document.get('extensionsUsed', []),
           'extensions_required': document.get('extensionsRequired', []),
           'glb_bytes': path.stat().st_size, 'external_decoders_required': False,
           'geometry': geometry, 'vertices': sum(g['vertices'] for g in geometry),
           'triangles': sum(g['triangles'] for g in geometry),
           'mesh_objects': [n.get('name') for n in document['nodes'] if 'mesh' in n],
           'max_export_influences': 4}
    if not finite or not joint_ranges_valid or not embedded or abs(min(weight_sums) - 1) > 0.001 or abs(max(weight_sums) - 1) > 0.001:
        raise RuntimeError(f'GLB binary validation failed: {raw}')
    # Fresh scene and actual glTF import: inspect the exported artifact, not just source.
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    before = set(bpy.data.actions)
    bpy.context.scene.render.fps = 30
    bpy.ops.import_scene.gltf(filepath=str(path), bone_shape_scale_factor=0.0)
    bpy.context.scene.render.fps = 30
    imported = [a for a in bpy.data.actions if a not in before]
    armature = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH'
              and any(m.type == 'ARMATURE' for m in o.modifiers)]
    for obj in list(bpy.context.scene.objects):
        if obj.type == 'MESH' and obj not in meshes:
            obj.hide_render = True  # glTF importer bone-widget geometry is not the asset.
    if len(armature.data.bones) != source_bone_count:
        raise RuntimeError('Roundtrip lost original bones')
    for track in armature.animation_data.nla_tracks:
        track.mute = True
    roundtrip = []
    actions = {}
    for spec in report:
        action = next((a for a in imported if a.name == spec['name'] or a.name.startswith(spec['name'] + '.')), None)
        if not action:
            raise RuntimeError(f'Missing roundtrip action {spec["name"]}')
        actions[spec['name']] = action
        set_action(armature, action)
        start, end = action.frame_range
        reset_pose(armature)
        minimum, maximum = math.inf, -math.inf
        worst_ground = 0.0
        root_xy = []
        lookup = bone_lookup(armature)
        sample_frames = [float(frame) for frame in range(math.ceil(start), math.floor(end) + 1)]
        if spec['name'] == 'Slide':
            sample_frames += [frame + 0.5 for frame in range(math.ceil(start), math.floor(end))]
        for frame in sorted(sample_frames):
            bpy.context.scene.frame_set(math.floor(frame), subframe=frame % 1)
            b = bounds(meshes)
            minimum = min(minimum, b['min'][2])
            maximum = max(maximum, b['max'][2])
            worst_ground = max(worst_ground, abs(b['min'][2]))
            root = armature.matrix_world @ armature.pose.bones[lookup['Hips'].name].head
            root_xy.append([root.x, root.y])
            if not b['finite']:
                raise RuntimeError('Nonfinite roundtrip geometry')
            if spec['name'] == 'Slide' and (b['max'][2] > 0.9001 or b['min'][2] < -0.02):
                raise RuntimeError(f'Roundtrip Slide failed {frame}: {b}')
        span = [max(p[i] for p in root_xy) - min(p[i] for p in root_xy) for i in range(2)]
        if max(span) > 0.001 or worst_ground > 0.003:
            raise RuntimeError(f'Root motion/ground drift after GLB roundtrip: {spec["name"]} {span} {worst_ground}')
        roundtrip.append({'name': spec['name'], 'minZ': minimum, 'maxZ': maximum,
                          'max_ground_error': worst_ground, 'hip_xy_span': span,
                          'frames_checked': math.floor(end) - math.ceil(start) + 1,
                          'samples_checked': len(sample_frames)})
    set_action(armature, None)
    reset_pose(armature)
    raw['roundtrip'] = roundtrip
    raw['roundtrip_rest_bounds'] = bounds(meshes)
    raw['roundtrip_bone_count'] = len(armature.data.bones)
    return raw, armature, meshes, actions


def render_views(directory, armature, actions, portrait=False, static_only=False):
    directory.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 32
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 720
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = 'AgX'
    scene.view_settings.exposure = 0
    world = bpy.data.worlds.new('CharacterInspectionWorld')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (0.15, 0.17, 0.20, 1)
    world.node_tree.nodes['Background'].inputs[1].default_value = 0.35
    scene.world = world
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, -0.008))
    ground = bpy.context.object
    mat = bpy.data.materials.new('InspectionGround')
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (0.10, 0.12, 0.14, 1)
    shader.inputs['Roughness'].default_value = 0.9
    ground.data.materials.append(mat)
    for name, location, energy, size in [('Key', (3, -4, 5), 450, 4), ('Fill', (-3, -2, 3), 220, 4), ('Rim', (1, 3, 4), 350, 3)]:
        data = bpy.data.lights.new(name, 'AREA')
        data.energy, data.shape, data.size = energy, 'DISK', size
        obj = bpy.data.objects.new(name, data)
        scene.collection.objects.link(obj)
        obj.location = location
        obj.rotation_euler = (Vector((0, 0, 0.9)) - obj.location).to_track_quat('-Z', 'Y').to_euler()
    camera_data = bpy.data.cameras.new('InspectionCamera')
    camera = bpy.data.objects.new('InspectionCamera', camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera_data.type = 'ORTHO'
    camera_data.ortho_scale = 2.45
    renders = []
    view_specs = [
        ('static_front', (0, -5, 1.2), None, 0, (0, 0, 0.91)),
        ('static_back', (0, 5, 1.2), None, 0, (0, 0, 0.91)),
        ('static_side', (5, 0, 1.2), None, 0, (0, 0, 0.91)),
        ('idle_front', (2.4, -5, 1.7), 'Idle', 0.25, (0, 0, 0.91)),
        ('run_front', (2.4, -5, 1.7), 'Run', 0.25, (0, 0, 0.91)),
        ('run_side', (5, 0, 1.5), 'Run', 0.25, (0, 0, 0.91)),
        ('slide_side', (5, 0, 1.2), 'Slide', 0.25, (0, -0.1, 0.55)),
        ('slide_front', (2.4, -5, 1.5), 'Slide', 0.25, (0, -0.1, 0.55)),
        ('jump_side', (5, 0, 1.5), 'Jump', 0.5, (0, 0, 0.91)),
    ]
    for name, position, clip, phase, target in (view_specs[:3] if static_only else view_specs):
        action = actions.get(clip)
        set_action(armature, action)
        reset_pose(armature)
        if action:
            start, end = action.frame_range
            scene.frame_set(round(start + (end - start) * phase))
        else:
            scene.frame_set(1)
        camera.location = position
        camera.rotation_euler = (Vector(target) - camera.location).to_track_quat('-Z', 'Y').to_euler()
        scene.render.filepath = str(directory / (name + '.png'))
        bpy.ops.render.render(write_still=True)
        renders.append(scene.render.filepath)
    if portrait:
        set_action(armature, None)
        reset_pose(armature)
        scene.frame_set(1)
        ground.hide_render = True
        scene.render.film_transparent = True
        scene.render.resolution_x = scene.render.resolution_y = 280
        camera_data.ortho_scale = 0.78
        camera.location = (0, -5, 1.53)
        camera.rotation_euler = (Vector((0, 0, 1.53)) - camera.location).to_track_quat('-Z', 'Y').to_euler()
        scene.render.image_settings.file_format = 'PNG'
        scene.render.image_settings.color_mode = 'RGBA'
        scene.render.filepath = str(directory / 'portrait.png')
        bpy.ops.render.render(write_still=True)
        renders.append(scene.render.filepath)
    return renders


def prepare_blend(source, output):
    """Load trusted data only; preserve the complete source and evaluated IK motion."""
    backup = output / 'source'
    backup.mkdir(exist_ok=True)
    shutil.copy2(source, backup / source.name)
    bpy.ops.wm.open_mainfile(filepath=str(source), use_scripts=False)
    rigs = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE'
            and any(m.type == 'ARMATURE' and m.object == o
                    for mesh in bpy.context.scene.objects if mesh.type == 'MESH' for m in mesh.modifiers)]
    if len(rigs) != 1:
        raise RuntimeError('Blend requires exactly one existing skin rig; automatic rebinding is not safe')
    arm = rigs[0]
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH'
              and any(m.type == 'ARMATURE' and m.object == arm for m in o.modifiers)]
    original = inspect(arm, meshes)
    original['collections'] = [{'name': c.name, 'objects': [o.name for o in c.objects]}
                               for c in bpy.data.collections]
    original['morphs'] = {o.name: [{'name': k.name, 'value': k.value}
                                 for k in o.data.shape_keys.key_blocks]
                          for o in meshes if o.data.shape_keys}
    original['constraints'] = {p.name: [{'type': c.type, 'influence': c.influence,
                                       'subtarget': getattr(c, 'subtarget', None)} for c in p.constraints]
                               for p in arm.pose.bones if p.constraints}
    # Archive source actions with evaluated constraints before modifying the hierarchy.
    source_actions = list(bpy.data.actions)
    captures = capture_original(arm, [a for a in source_actions if action_is_moving(a)
                                      and any(s.target_id_type == 'OBJECT' for s in a.slots)], bpy.context.scene)
    for action in source_actions:
        action.name = 'Original_' + action.name
        action.use_fake_user = True
    for p in arm.pose.bones:
        for c in p.constraints:
            p.constraints.remove(c)
    arm.animation_data_clear()
    baked = []
    for name, start, end, samples in captures:
        action = bpy.data.actions.new('SourceBaked_' + name)
        set_action(arm, action)
        for frame, matrices in samples:
            bpy.context.scene.frame_set(frame)
            for bone in arm.data.bones:
                desired = arm.matrix_world.inverted() @ matrices[bone.name]
                parent = arm.matrix_world.inverted() @ matrices[bone.parent.name] if bone.parent else Matrix.Identity(4)
                pb = arm.pose.bones[bone.name]
                pb.rotation_mode = 'QUATERNION'
                pb.matrix_basis = bone.convert_local_to_pose(desired, bone.matrix_local,
                    parent_matrix=parent, parent_matrix_local=bone.parent.matrix_local if bone.parent else Matrix.Identity(4), invert=True)
                for path in ('location', 'rotation_quaternion', 'scale'):
                    pb.keyframe_insert(path, frame=frame)
        action.use_fake_user = True
        baked.append(action.name)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(backup / 'evaluated_source_motion.blend'))
    original['evaluated_source_actions'] = baked
    # The exact original default eye expression is restored, not redesigned.
    arm.animation_data_clear()
    reset_pose(arm)
    for obj in meshes:
        if obj.data.shape_keys:
            obj.data.shape_keys.animation_data_clear()
            for spec in original['morphs'][obj.name]:
                obj.data.shape_keys.key_blocks[spec['name']].value = spec['value']
    for obj in list(bpy.context.scene.objects):
        if obj not in [arm, *meshes]:
            bpy.data.objects.remove(obj, do_unlink=True)
    for track in list(arm.animation_data.nla_tracks) if arm.animation_data else []:
        arm.animation_data.nla_tracks.remove(track)
    # Apply authored shell thickness before scaling, keeping exact surface geometry.
    for obj in meshes:
        bpy.context.view_layer.objects.active = obj
        obj.hide_set(False)
        for modifier in list(obj.modifiers):
            if modifier.type != 'ARMATURE':
                bpy.ops.object.modifier_apply(modifier=modifier.name)
        # Source contains a few float weights 1.0000001. Clamp numeric noise only.
        for vertex in obj.data.vertices:
            for group in vertex.groups:
                if group.weight > 1.0:
                    obj.vertex_groups[group.group].add([vertex.index], 1.0, 'REPLACE')
        if obj.data.validate(clean_customdata=False):
            raise RuntimeError(f'Unexpected topology repair required: {obj.name}')
    mapping = {'Hips': 'Bone.005', 'Spine': 'Bone.001', 'Spine2': 'chest control',
               'Neck': 'Bone.003', 'Head': 'head'}
    for side, suffix in [('Left', 'L'), ('Right', 'R')]:
        mapping.update({side + 'Shoulder': 'Bone.' + suffix,
                        side + 'Arm': 'Bone.' + suffix + '.001',
                        side + 'ForeArm': 'Bone.' + suffix + '.002',
                        side + 'Hand': 'hand control.' + suffix,
                        side + 'UpLeg': 'Bone.' + suffix + '.004',
                        side + 'Leg': 'Bone.' + suffix + '.005',
                        side + 'Foot': 'foot control.' + suffix,
                        side + 'ToeBase': 'Bone.' + suffix + '.007'})
    if not all(n in arm.data.bones for n in mapping.values()):
        raise RuntimeError('Unsupported blend rig: explicit reviewed rig mapping required')
    for semantic, name in mapping.items():
        arm.data.bones[name].name = semantic  # Blender also updates original vertex groups.
    # Original IK targets are the weighted foot/hand bones. FK export must connect
    # them to the original deform limbs; rest matrices and skin weights stay intact.
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    for side in ('Left', 'Right'):
        arm.data.edit_bones[side + 'Foot'].parent = arm.data.edit_bones[side + 'Leg']
        arm.data.edit_bones[side + 'Hand'].parent = arm.data.edit_bones[side + 'ForeArm']
    bpy.ops.object.mode_set(mode='OBJECT')
    original['rig_mapping'] = mapping
    original['runtime_rig_policy'] = 'Original rest matrices and skin; weighted IK targets reparented to deform limbs for baked FK. Original IK and evaluated motion archived in source/.'
    return arm, meshes, original


def blend_materials(meshes, directory):
    """Lossless Diffuse-color translation, fail closed for unknown custom shaders."""
    for mat in {s.material for o in meshes for s in o.material_slots if s.material}:
        tree = mat.node_tree
        output = next(n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output)
        shader = output.inputs['Surface'].links[0].from_node
        if shader.type == 'BSDF_DIFFUSE':
            pbr = tree.nodes.new('ShaderNodeBsdfPrincipled')
            pbr.inputs['Base Color'].default_value = shader.inputs['Color'].default_value
            for link in shader.inputs['Color'].links:
                tree.links.new(link.from_socket, pbr.inputs['Base Color'])
            pbr.inputs['Roughness'].default_value = 1
            pbr.inputs['Specular IOR Level'].default_value = 0
            tree.links.new(pbr.outputs['BSDF'], output.inputs['Surface'])
        elif shader.type != 'BSDF_PRINCIPLED':
            raise RuntimeError(f'Custom shader needs explicit basecolor bake: {mat.name}')
    result = extract_materials(meshes, directory)
    # extract_materials has a legacy Ch09 dielectric policy; cat keeps pure diffuse.
    for mat in {s.material for o in meshes for s in o.material_slots if s.material}:
        pbr = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        pbr.inputs['Roughness'].default_value = 1
        pbr.inputs['Specular IOR Level'].default_value = 0
    result['specular_policy'] = 'Original pure Diffuse translated to roughness=1, specular=0; identical source texture and black shell color, no recoloring or lighting baked.'
    return result


def render_source_reference(source, output, height):
    bpy.ops.wm.open_mainfile(filepath=str(source), use_scripts=False)
    arm = bpy.data.objects.get('Armature')
    if not arm or arm.type != 'ARMATURE':
        raise RuntimeError('Source reference requires reviewed Armature rig')
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH'
              and any(m.type == 'ARMATURE' and m.object == arm for m in o.modifiers)]
    arm.animation_data_clear()
    reset_pose(arm)
    arm.data.pose_position = 'REST'
    for obj in meshes:
        if obj.data.shape_keys:
            obj.data.shape_keys.animation_data_clear()
    for obj in list(bpy.context.scene.objects):
        if obj not in [arm, *meshes]:
            bpy.data.objects.remove(obj, do_unlink=True)
    b = bounds(meshes)
    scale = height / b['dimensions'][2]
    transform = Matrix.Translation(Vector((-(b['min'][0] + b['max'][0]) * scale / 2,
                                           -(b['min'][1] + b['max'][1]) * scale / 2,
                                           -b['min'][2] * scale))) @ Matrix.Scale(scale, 4)
    worlds = {o: o.matrix_world.copy() for o in [arm, *meshes]}
    for obj in [arm, *meshes]:
        obj.parent = None
        obj.matrix_world = transform @ worlds[obj]
    paths = render_views(output / 'renders' / 'source_reference', arm, {}, static_only=True)
    print('SOURCE_REFERENCE=' + json.dumps(paths))


def main():
    args = arguments()
    source = args.input.expanduser().resolve()
    output = args.output_dir.expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in {'.fbx', '.blend'}:
        raise RuntimeError('Input must be an existing FBX or blend file')
    is_blend = source.suffix.lower() == '.blend'
    if is_blend and args.texture_size is None:
        args.texture_size = 2048
    if args.texture_size is not None and args.texture_size <= 0:
        raise RuntimeError('Texture size must be a positive integer')
    if args.height <= 0 or not math.isfinite(args.height):
        raise RuntimeError('Height must be positive and finite')
    if output == source.parent or source.is_relative_to(output):
        raise RuntimeError('Output must not contain the original source')
    output.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if args.source_reference_only:
        if not is_blend:
            raise RuntimeError('Source reference mode is for blend inputs only')
        render_source_reference(source, output, args.height)
        if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
            raise RuntimeError('Source changed')
        return
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    if is_blend:
        armature, meshes, original = prepare_blend(source, output)
        captures = []  # Nonsemantic source performance is archived, not mislabeled as Run.
        materials = blend_materials(meshes, output / 'textures')
    else:
        bpy.ops.import_scene.fbx(filepath=str(source), use_anim=True)
        armatures = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
        meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
        if len(armatures) != 1:
            raise RuntimeError(f'Expected one skin rig, found {len(armatures)}')
        armature = armatures[0]
        bpy.context.scene.render.fps = 30
        original = inspect(armature, meshes)
        captures = capture_original(armature, [a for a in bpy.data.actions if action_is_moving(a)], bpy.context.scene)
        materials = extract_materials(meshes, output / 'textures')
    scene = bpy.context.scene
    scene.render.fps = 30
    overrides = []
    for spec in args.clip_override:
        capture, record = capture_clip_override(armature, spec, output)
        if any(item['name'] == record['name'] for item in overrides):
            raise RuntimeError(f'Duplicate clip override: {record["name"]}')
        captures = [item for item in captures if record['name'].lower() not in item[0].lower()]
        captures.append(capture)
        overrides.append(record)
    transform, normalization = normalize(armature, meshes, args.height)
    actions, clips = make_clips(armature, meshes, captures, transform)
    for clip in clips:
        override = next((item for item in overrides if item['name'] == clip['name']), None)
        if override:
            clip['origin'] = 'matching_rig_fbx_animation_override'
            clip['source'] = override['source']
    bpy.ops.object.select_all(action='DESELECT')
    for obj in [armature, *meshes]:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = armature
    scene.frame_set(1)
    blend = output / 'imported.blend'
    # Packed textures and all bones; inspection lights never contaminate production blend.
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    materials['export_texture_size'] = args.texture_size
    materials['export_copies'] = resize_export_images(meshes, output / 'export_textures', args.texture_size)
    exports = output / 'exports'
    exports.mkdir(exist_ok=True)
    glb = exports / (source.stem + '.glb' if is_blend else 'ch09.glb')
    # Muted NLA tracks are explicitly included by unmuting for track export.
    for track in armature.animation_data.nla_tracks:
        track.mute = False
    bpy.ops.export_scene.gltf(filepath=str(glb), export_format='GLB', use_selection=True,
        export_yup=True, export_animations=True, export_animation_mode='NLA_TRACKS',
        export_force_sampling=True, export_frame_range=False, export_anim_slide_to_zero=True,
        export_anim_scene_split_object=False, export_anim_single_armature=True,
        export_skins=True, export_all_influences=False, export_def_bones=False,
        export_rest_position_armature=True, export_materials='EXPORT', export_image_format='AUTO',
        export_draco_mesh_compression_enable=False)
    original_max_influences = max(len([g for g in v.groups if g.weight > 0])
                                  for obj in meshes for v in obj.data.vertices)
    expected_mesh_names = {obj.name for obj in meshes}
    validation, roundtrip_arm, _, roundtrip_actions = validate_glb(glb, clips, len(original['bones']))
    validation['three_skin_policy'] = 'GLB uses four largest normalized influences; blend retains all original weights'
    validation['original_max_influences'] = original_max_influences
    if is_blend and set(validation['mesh_objects']) != expected_mesh_names:
        raise RuntimeError('GLB export omitted an original character surface mesh')
    if args.texture_size is not None and any(max(image['size']) > args.texture_size
                                             for image in validation['images']):
        raise RuntimeError('Exported texture exceeds requested size')
    renders = ([str(p) for p in sorted((output / 'renders').glob('*.png'))] if args.skip_render
               else render_views(output / 'renders', roundtrip_arm, roundtrip_actions, portrait=is_blend))
    source_renders = [str(p) for p in sorted((output / 'renders' / 'source_reference').glob('*.png'))]
    unchanged = hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    if not unchanged:
        raise RuntimeError('Source changed during import')
    manifest = {'schema_version': 1, 'source': str(source), 'source_sha256': source_hash,
                'source_unchanged': unchanged, 'blender_version': bpy.app.version_string,
                'original': original, 'normalization': normalization, 'textures': materials,
                'clips': clips, 'clip_overrides': overrides, 'validation': validation,
                'outputs': {'blend': str(blend), 'glb': str(glb), 'renders': renders,
                            'source_reference_renders': source_renders},
                'character_slots': ['original classic', 'ch09', 'cat'] if is_blend else None,
                'runtime_content_rotation_y': math.pi if is_blend else None,
                'limitations': ['Source attribution and license were not supplied and are not inferred.',
                    ('No moving source animation; generated clips are procedural, not motion capture.'
                     if not captures and not is_blend else ('Original nonsemantic motion and IK bake archived separately; four gameplay clips procedurally adapted to original skin.' if is_blend else 'Source motion was retained; missing functional clips are procedural.')),
                    'GLB weights use the largest four influences for standard Three.js skinning; blend keeps original full weights.',
                    'Jump contains skeletal anticipation/tuck/landing only; gameplay supplies vertical displacement.',
                    'Slide is a low held pose; gameplay must switch into/out of it rather than blend from standing under an obstacle.',
                    ('Diffuse surface translated directly to PBR; glTF cannot carry Blender eye UI controls or IK constraints. Original UI, rig, source actions and full 4K texture are archived.' if is_blend else
                     'Non-PBR gloss conversion is an approximation; source diffuse, normal and original specular/gloss files are preserved.')]}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
    print('CHARACTER_IMPORT_RESULT=' + json.dumps({'glb': str(glb), 'normalization': normalization,
                                                'clips': clips, 'validation': validation}, ensure_ascii=False))


if __name__ == '__main__':
    main()
