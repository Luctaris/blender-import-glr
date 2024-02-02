import os
import struct
import bpy
import bmesh
import re

### Import Plugin Entry Point
def load(context, **keywords):
    if keywords['files'][0].name == '':
        raise RuntimeError('No .glr files have been selected for import!')

    filter_list = []

    if len(keywords['filter_list']) != 0:
        raw_filter_list_str = keywords['filter_list'] + ','
        if not re.search('^([A0-F9]{16},|NO_TEXTURE,)+$', raw_filter_list_str):
            raise RuntimeError('Invalid filter textures list provided')
        dup_filter_list = raw_filter_list_str[:-1].split(',')
        filter_list = [*set(dup_filter_list)] # remove duplicates

    dir_name = os.path.dirname(keywords['filepath'])
    obs = []

    for glr_file in keywords['files']:
        filepath = os.path.join(dir_name, glr_file.name)
        triangle_options = (
            keywords['enable_mat_transparency'],
            keywords['enable_bf_culling'],
            keywords['filter_mode'],
            filter_list,
            keywords['gen_light_color_attribute'],
            keywords['gen_overlay_color_attribute']
        )
        ob = load_glr(filepath, triangle_options)
        obs.append(ob)

    # Objects created by op are selected, active, placed at cursor, and transformed
    if bpy.ops.object.select_all.poll():
        bpy.ops.object.select_all(action='DESELECT')
    for ob in obs:
        ob.select_set(True)
        ob.location = bpy.context.scene.cursor.location
        ob.location = ob.location + keywords['move']
        ob.rotation_euler = keywords['rotation']
        ob.scale = keywords['scale']
        if keywords['merge_doubles']:
            ob_mesh = ob.data
            bm = bmesh.new()
            bm.from_mesh(ob_mesh)
            merge_distance = round(keywords['merge_distance'], 6) # chopping off extra precision
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge_distance)
            bm.to_mesh(ob_mesh)
    bpy.context.view_layer.objects.active = obs[0]

    # Checking and enabling Color Management options
    if keywords['enable_srgb']:
        bpy.context.scene.display_settings.display_device = 'sRGB'
        bpy.context.scene.view_settings.view_transform = 'Standard'
        bpy.context.scene.sequencer_colorspace_settings.name = 'sRGB'

    return {'FINISHED'}


def load_glr(filepath, triangle_options):
    texture_dir = os.path.abspath(os.path.dirname(filepath))
    with open(filepath, 'rb') as fb:
        return GlrImporter(fb, texture_dir, triangle_options).load()


class GlrImporter:
    def __init__(self, fb, texture_dir, triangle_options):
        self.fb = fb
        self.texture_dir = texture_dir
        self.show_alpha = triangle_options[0]
        self.display_culling = triangle_options[1]
        self.filter_mode = triangle_options[2]
        self.filter_list = triangle_options[3]
        self.gen_light_color_attribute = triangle_options[4]
        self.gen_overlay_color_attribute = triangle_options[5]
        self.obj_name = None
        self.num_tris = None
        self.microcode = None

    def load(self):
        self.load_header()
        return self.do_tris()

    def load_header(self):
        fb = self.fb

        # Check magic
        if fb.read(6) != b'GL64R\0':
            raise RuntimeError('Not a valid glr file')

        # Check version
        version = struct.unpack('<H', fb.read(2))[0]
        if version > 0 and version < 2:
            raise RuntimeError(f'Outdated glr file format detected ({version}), please update the glr import addon')
        elif version != 2:
            raise RuntimeError(f'Unknown N64 Ripper version ({version}) encountered')

        romname = fb.read(20)
        romname = romname.decode(errors='replace')
        romname = romname.replace('\0', '').strip()
        romname = romname or 'Unknown N64 Game'
        self.obj_name = romname + ' (' + os.path.basename(fb.name)[:-4] + ')'

        self.num_tris = struct.unpack('<I', fb.read(4))[0]
        self.microcode = struct.unpack('<I', fb.read(4))[0]

    def do_tris(self):
        fb = self.fb

        verts = []
        faces = []
        shade_colors = []
        prim_colors = []
        env_colors = []
        blend_colors = []
        fog_colors = []
        uvs0 = []
        uvs1 = []

        matinfo_cache = {}
        face_materials = []

        for i in range(self.num_tris):
            tmp_shade_cols = []
            tmp_uvs0 = []
            tmp_uvs1 = []
            tmp_verts = []
            tmp_face = []

            # Read vertices
            for j in range(3):
                (
                    x, y, z, r, g, b, a, s0, t0, s1, t1,
                ) = struct.unpack('<11f', fb.read(44))

                # delay writing lists for filter check
                tmp_shade_cols += [r, g, b, a]
                tmp_uvs0 += [s0, t0]
                tmp_uvs1 += [s1, t1]
                tmp_verts.append((x, -z, y))  # Yup2Zup
                tmp_face.append((len(verts)) + j)

            # Read triangle data
            (
                fog_r, fog_g, fog_b, fog_a,
                blend_r, blend_g, blend_b, blend_a,
                env_r, env_g, env_b, env_a,
                prim_r, prim_g, prim_b, prim_a,
                prim_l, prim_m,
                fog_multiplier, fog_offset,
                k4, k5,
                combiner_mux,
                other_mode,
                geometry_mode,
                tex0_crc,
                tex0_maskS, tex0_maskT,
                tex0_wrapS, tex0_wrapT,
                tex1_crc,
                tex1_maskS, tex1_maskT,
                tex1_wrapS, tex1_wrapT,
            ) = struct.unpack('<4f4f4f4f2f2f2iQQIQ4BQ4B', fb.read(132))

            tex0_crc_hex = f'{tex0_crc:016X}'

            if self.filter_mode: # Blacklist mode
                if tex0_crc_hex in self.filter_list or \
                    (tex0_crc == 0 and 'NO_TEXTURE' in self.filter_list):
                        continue # skip tri, go to the next one
            else: # Whitelist mode, opposite of blacklist
                if tex0_crc_hex not in self.filter_list or \
                    (tex0_crc == 0 and 'NO_TEXTURE' not in self.filter_list):
                        continue

            # write delayed info
            shade_colors.extend(tmp_shade_cols)
            uvs0.extend(tmp_uvs0)
            uvs1.extend(tmp_uvs1)
            verts.extend(tmp_verts)
            faces.append(tmp_face)

            # Store per-tri colors as vertex colors (once per corner)
            prim_colors += [prim_r, prim_g, prim_b, prim_a] * 3
            env_colors += [env_r, env_g, env_b, env_a] * 3
            blend_colors += [blend_r, blend_g, blend_b, blend_a] * 3
            fog_colors += [fog_r, fog_g, fog_b, fog_a] * 3

            # Create combination light/overlay color attributes
            # TODO: Implement correctly based on color attributes actively used by each seperate material
            '''
            for _ in range(3):
                merged_r = shade_colors[curr_vert] * prim_colors[curr_vert] * env_colors[curr_vert]
                curr_vert += 1
                merged_g = shade_colors[curr_vert] * prim_colors[curr_vert] * env_colors[curr_vert]
                curr_vert += 1
                merged_b = shade_colors[curr_vert] * prim_colors[curr_vert] * env_colors[curr_vert]
                curr_vert += 1
                merged_a = shade_colors[curr_vert] * prim_colors[curr_vert] * env_colors[curr_vert]
                curr_vert += 1
                merged_colors += [merged_r, merged_g, merged_b, merged_a]
            '''

            # Gather all the info we need to make the material for this tri
            matinfo = (
                combiner_mux,
                other_mode,
                geometry_mode,
                tex0_crc,
                tex0_wrapS, tex0_wrapT,
                tex1_crc,
                tex1_wrapS, tex1_wrapT,
            )
            material_index = matinfo_cache.setdefault(matinfo, len(matinfo_cache))
            face_materials.append(material_index)

        # Create mesh
        mesh = bpy.data.meshes.new(self.obj_name)
        mesh.from_pydata(verts, [], faces)

        # Create & assign materials
        for matinfo in matinfo_cache:
            mesh.materials.append(self.create_material(matinfo))
        mesh.polygons.foreach_set('material_index', face_materials)

        # Create attributes
        mesh.vertex_colors.new(name='Shading').data.foreach_set('color', shade_colors)
        mesh.vertex_colors.new(name='Primitive').data.foreach_set('color', prim_colors)
        mesh.vertex_colors.new(name='Environment').data.foreach_set('color', env_colors)
        mesh.vertex_colors.new(name='Blend').data.foreach_set('color', blend_colors)
        mesh.vertex_colors.new(name='Fog').data.foreach_set('color', fog_colors)
        if self.gen_light_color_attribute:
            mesh.vertex_colors.new(name='Light').data.foreach_set('color', light_colors)
        if self.gen_overlay_color_attribute:
            mesh.vertex_colors.new(name='Light').data.foreach_set('color', light_colors)
        mesh.uv_layers.new(name='UV0').data.foreach_set('uv', uvs0)
        mesh.uv_layers.new(name='UV1').data.foreach_set('uv', uvs1)

        mesh.validate()

        # Create object
        ob = bpy.data.objects.new(mesh.name, mesh)
        bpy.context.scene.collection.objects.link(ob)

        return ob

    def create_material(self, matinfo):
        (
            combiner_mux,
            other_mode,
            geometry_mode,
            tex0_crc,
            tex0_wrapS, tex0_wrapT,
            tex1_crc,
            tex1_wrapS, tex1_wrapT,
        ) = matinfo

        cycle_type = (other_mode >> 52) & 0x3
        two_cycle_mode = cycle_type == 1  # 0 = 1CYCLE, 1 = 2CYCLE

        combiner1, combiner2 = decode_combiner_mode(combiner_mux)
        blender1, blender2 = decode_blender_mode(other_mode)

        if not two_cycle_mode:
            combiner2 = blender2 = None

        def make_tex_dict(crc, wrapS, wrapT):
            tex = {}
            tex['filepath'] = self.get_texture_path_for_crc(crc)
            tex['filter'] = get_texture_filter(other_mode)
            tex['wrapS'] = get_texture_wrap_mode(wrapS)
            tex['wrapT'] = get_texture_wrap_mode(wrapT)
            tex['wrapST'] = get_combined_texture_wrap_modes(tex['wrapS'][0], tex['wrapT'][0])
            tex['crc'] = crc
            return tex

        tex0 = make_tex_dict(tex0_crc, tex0_wrapS, tex0_wrapT)
        tex1 = make_tex_dict(tex1_crc, tex1_wrapS, tex1_wrapT)
        tex0['uv_map'] = 'UV0'
        tex1['uv_map'] = 'UV1'

        # Determine backface culling
        # F3D/F3DEX: 0x2000 (0010 0000 0000 0000)
        # F3DEX2: 0x400 (0100 0000 0000)
        # TODO: Check others, assumed under F3D/F3DEX family
        bfc_mask = 0x2000
        if( self.microcode == 2 or  # F3DEX2
            self.microcode == 5 or  # L3DEX2
            self.microcode == 7 or  # S2DEX2
            self.microcode == 13 or # F3DEX2CBFD
            self.microcode == 17 or # F3DZEX2OOT
            self.microcode == 18 or # F3DZEX2MM
            self.microcode == 21):  # F3DEX2ACCLAIM
                bfc_mask >>= 3

        cull_backface = bool(geometry_mode & bfc_mask)

        mat_name = self.get_material_name_for_crcs_and_wrapmodes(
            [tex0_crc, tex1_crc],
            [tex0['wrapST'], tex1['wrapST']],
            cull_backface)

        found_mat_index = bpy.data.materials.find(mat_name)

        if found_mat_index != -1:
            mat = bpy.data.materials[found_mat_index]
        else:
            mat = bpy.data.materials.new(mat_name)

            setup_n64_material(
                mat,
                combiner1, combiner2,
                blender1, blender2,
                tex0, tex1,
                cull_backfacing=cull_backface & self.display_culling,
                show_alpha=self.show_alpha,
            )
        return mat

    def get_texture_path_for_crc(self, crc):
        if crc != 0:
            return os.path.join(self.texture_dir, f'{crc:016X}.png')
        else:
            return ''

    def get_material_name_for_crcs_and_wrapmodes(self, tex_crc, tex_wrapmodes, cull_backfaces):
        if tex_crc[0] == 0: # Either invalid crc combo (tex0_crc == 0, tex1_crc != 0), or both crcs are null (0)
            return 'NO_TEXTURE'
        returning_str = ''
        for i in range(2):
            if tex_crc[i] != 0:
                if i == 1:
                    returning_str += ' : ' # using T1, add material seperator
                returning_str += f'{tex_crc[i]:016X}'
                if tex_wrapmodes[i] != 'R': # if both wrap S and T are Repeat, don't include wrapmode indicator
                    returning_str += f'({tex_wrapmodes[i]})'
        if not cull_backfaces:
            returning_str += ' | (N)'
        return returning_str

# Imported materials are supposed to perform (highly simplified) high
# level emulation of the N64's RDP pixel shader pipeline.
#
# OVERVIEW OF THE RDP
#
#   ┌───────────┐
#   │ Texture 0 ├──┐
#   └───────────┘  │
#   ┌───────────┐  └───►┌────────────────┐      ┌─────────┐ Output
#   │ Texture 1 ├──────►│ Color Combiner ├─────►│ Blender ├────────►
#   └───────────┘  ┌───►└────────────────┘ ┌───►└─────────┘
#    Colors, etc.  │                       │
#   ───────────────┴───────────────────────┘
#
# COLOR COMBINER
#
# The color combiner is used for effects like combining the texture and
# shading color. It combines four input variables, a, b, c, d, with the
# formula
#
#   Output = (a - b) * c + d
#
# RGB and Alpha are combined separately. In two-cycle mode the color
# combiner runs twice, and the second run can use the output from the
# first run as one of its inputs. Altogether that's 16 inputs in total.
#
#   (4 variables) * (2 RGB/Alpha) * (2 1st/2nd cycle) = 16
#
# The combiner is configured with a 64-bit mux value that specifies the
# source for the each of the 16 inputs.
#
# BLENDER
#
# The blender is used for effects like alpha blending and fog. Similar
# to the combiner, it combines two RGB colors, p and m, with two
# weights, a and b, using the formula
#
#   Output = (p * a + m * b) / (a + b)
#
# Unlike the combiner, it can use the current pixel in the framebuffer
# as input. It, too, can run in two-cycle mode.
#
# REFERENCES
# http://n64devkit.square7.ch/tutorial/graphics/
# http://n64devkit.square7.ch/pro-man/pro12/index.htm
# https://hack64.net/wiki/doku.php?id=rcpstructs
# Angrylion's RDP Plus


def setup_n64_material(
    mat,
    combiner1, combiner2,
    blender1, blender2,
    tex0, tex1,
    cull_backfacing,
    show_alpha,
):
    mat.shadow_method = 'NONE'
    mat.blend_method = 'OPAQUE'
    mat.use_backface_culling = cull_backfacing

    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # Gather all input sources the RDP will need
    sources = set()
    sources.update(combiner1)
    sources.update(combiner2 or [])
    sources.update(blender1)
    sources.update(blender2 or [])

    # TODO: node positions needs a loooot of work
    x, y = 200, 100

    # Create nodes for the input sources
    input_map = make_rdp_input_nodes(mat, sources, tex0, tex1, location=(-200, 0))

    # 1st Color Combiner cycle

    input_map['Combined Color'] = 1.0
    input_map['Combined Alpha'] = 1.0

    node_comb1 = nodes.new('ShaderNodeGroup')
    node_comb1.width = 220
    node_comb1.location = x, y
    x, y = x + 400, y - 200
    node_comb1.node_tree = get_combiner_group()

    for i in range(8):
        connect_input(mat, input_map[combiner1[i]], node_comb1.inputs[i])

    input_map['Combined Color'] = node_comb1.outputs[0]
    input_map['Combined Alpha'] = node_comb1.outputs[1]

    # 2nd Color Combiner cycle

    # Skip the 2nd cycle if it does nothing; two-cycle mode is probably
    # only enabled for a blender effect.
    if combiner2 == ('0', '0', '0', 'Combined Color', '0', '0', '0', 'Combined Alpha'):
        combiner2 = None

    if combiner2:
        node_comb2 = nodes.new('ShaderNodeGroup')
        node_comb2.width = 220
        node_comb2.location = x, y
        x, y = x + 400, y - 200
        node_comb2.node_tree = get_combiner_group()

        for i in range(8):
            connect_input(mat, input_map[combiner2[i]], node_comb2.inputs[i])

        input_map['Combined Color'] = node_comb2.outputs[0]
        input_map['Combined Alpha'] = node_comb2.outputs[1]

    # Next the blender
    # It's poorly implemented atm...

    x, y = x + 200, y - 100

    # Handle some cases where the blender formula is particularly simple
    # TODO: disable until fog is correctly implemented
    '''
    node_blnd1 = make_simple_blender_lerp_node(mat, blender1, input_map)
    if blender2:
        node_blnd2 = make_simple_blender_lerp_node(mat, blender2, input_map)
    '''

    # If the last step of the blender reads the framebuffer color at
    # all, we crudely assume it's doing alpha blending
    last_blender = blender2 or blender1  # whichever comes last
    if 'Framebuffer Color' in last_blender:
        node_mixtr = nodes.new('ShaderNodeMixShader')
        node_trans = nodes.new('ShaderNodeBsdfTransparent')

        connect_input(mat, input_map['Combined Alpha'], node_mixtr.inputs[0])
        connect_input(mat, node_trans.outputs[0], node_mixtr.inputs[1])
        connect_input(mat, input_map['Combined Color'], node_mixtr.inputs[2])

        node_trans.location = x, y - 100
        node_mixtr.location = x + 200, y
        x, y = x + 500, y

        input_map['Combined Color'] = node_mixtr.outputs[0]

        if show_alpha:
            mat.blend_method = 'HASHED'

    # TODO: alpha compare

    node_out = nodes.new('ShaderNodeOutputMaterial')
    node_out.location = x, y
    links.new(input_map['Combined Color'], node_out.inputs[0])

    # Custom props (useful for debugging)
    mat['n64:01 Color Combiner'] = show_combiner_formula(*combiner1[:4])
    mat['n64:02 Alpha Combiner'] = show_combiner_formula(*combiner1[4:])
    mat['n64:03 2nd Color Combiner'] = show_combiner_formula(*combiner2[:4]) if combiner2 else ''
    mat['n64:04 2nd Alpha Combiner'] = show_combiner_formula(*combiner2[4:]) if combiner2 else ''
    mat['n64:05 Blender'] = show_blender_formula(*blender1)
    mat['n64:06 2nd Blender'] = show_blender_formula(*blender2) if blender2 else ''


def connect_input(mat, input, socket):
    # Connects input -> socket
    # Input can be either an output socket or a constant

    if isinstance(input, (int, float)):
        if socket.type == 'RGBA':
            socket.default_value = (input, input, input, 1.0)
        else:
            socket.default_value = input
    else:
        mat.node_tree.links.new(input, socket)


def make_rdp_input_nodes(mat, sources, tex0, tex1, location):
    # Given a list of input sources, creates the nodes needed to supply
    # those inputs. Returns a mapping from input source names to the
    # socket (or constant) you should use for that input.

    input_map = {
        '0': 0.0,
        '1': 1.0,
    }
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    x, y = location

    # Texture inputs
    for i in range(2):
        tex = tex0 if i == 0 else tex1
        if f'Texel {i} Color' in sources or f'Texel {i} Alpha' in sources:
            if tex['crc'] != 0:
                node = make_texture_node(mat, tex, i, location=(x, y))
                y -= 300
            input_map[f'Texel {i} Color'] = node.outputs['Color']
            input_map[f'Texel {i} Alpha'] = node.outputs['Alpha']

    # Vertex Color inputs
    for vc in ['Shading', 'Primitive', 'Environment', 'Blend', 'Fog']:
        if f'{vc} Color' in sources or f'{vc} Alpha' in sources:
            node = nodes.new('ShaderNodeVertexColor')
            node.location = x, y
            y -= 200
            node.layer_name = vc
            node.name = node.label = vc
            input_map[f'{vc} Color'] = node.outputs['Color']
            input_map[f'{vc} Alpha'] = node.outputs['Alpha']

    # LOD Fraction is not implemented; always use 0 for now in
    # the hopes this will select the highest detail mipmap...
    for src in ['LOD Fraction', 'Primitive LOD Fraction']:
        if src in sources:
            node = nodes.new('ShaderNodeValue')
            node.name = node.label = src
            node.location = x, y
            y -= 200
            node.outputs['Value'].default_value = 0
            input_map[src] = node.outputs['Value']

    # Not yet implemented
    unimplemented = [
        'Key Center',
        'Key Scale',
        'Noise',
        'Convert K4',
        'Convert K5',
    ]
    for un_src in unimplemented:
        if un_src in sources:
            print('Unimplemented color combiner input:', un_src)
            node = nodes.new('ShaderNodeRGB')
            node.location = x, y
            y += 300
            node.outputs[0].default_value = (0.0, 1.0, 1.0, 1.0)
            node.label = f'UNIMPLEMENTED {un_src}'
            input_map[un_src] = node.outputs[0]

    return input_map


def load_image(filepath):
    try:
        image = bpy.data.images.load(filepath, check_existing=True)
    except Exception:
        # Image didn't exist
        # Allow the path to be resolved later
        image = bpy.data.images.new(os.path.basename(filepath), 16, 16)
        image.filepath = filepath
        image.source = 'FILE'
    return image


def make_texture_node(mat, tex, tex_num, location):
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    x, y = location

    # Image Texture node
    node_tex = nodes.new('ShaderNodeTexImage')
    node_tex.name = node_tex.label = 'Texture 0' if tex_num == 0 else 'Texture 1'
    node_tex.width = 290
    node_tex.location = x - 150, y
    if tex['filepath']:
        node_tex.image = load_image(tex['filepath'])
    node_tex.interpolation = tex['filter']
    uv_socket = node_tex.inputs[0]

    x -= 370

    # Wrapping
    wrapS, wrapT = tex['wrapS'], tex['wrapT']
    if wrapS == wrapT == 'Repeat':
        node_tex.extension = 'REPEAT'
    elif wrapS == wrapT == 'Clamp':
        node_tex.extension = 'EXTEND'
    else:
        # Use math nodes to emulate other wrap modes

        node_tex.extension = 'EXTEND'

        frame = nodes.new('NodeFrame')
        frame.label = f'{wrapS} ({wrapS[0]}) x {wrapT} ({wrapT[0]})'

        # Combine XYZ
        node_com = nodes.new('ShaderNodeCombineXYZ')
        node_com.parent = frame
        node_com.location = x - 80, y - 110
        links.new(uv_socket, node_com.outputs[0])
        u_socket = node_com.inputs[0]
        v_socket = node_com.inputs[1]

        x -= 120

        for i in [0, 1]:
            wrap = wrapS if i == 0 else wrapT
            socket = node_com.inputs[i]

            if wrap == 'Repeat':
                node_math = nodes.new('ShaderNodeMath')
                node_math.parent = frame
                node_math.location = x - 140, y + 30 - i*200
                node_math.operation = 'WRAP'
                node_math.inputs[1].default_value = 0
                node_math.inputs[2].default_value = 1
                links.new(socket, node_math.outputs[0])
                socket = node_math.inputs[0]

            elif wrap == 'Mirror':
                node_math = nodes.new('ShaderNodeMath')
                node_math.parent = frame
                node_math.location = x - 140, y + 30 - i*200
                node_math.operation = 'PINGPONG'
                node_math.inputs[1].default_value = 1
                links.new(socket, node_math.outputs[0])
                socket = node_math.inputs[0]

            else:
                # Clamp doesn't require a node since the default on the
                # Texture node is EXTEND.
                # Adjust node location for aesthetics though.
                if i == 0:
                    node_com.location[1] += 90

            if i == 0:
                u_socket = socket
            else:
                v_socket = socket

        x -= 180

        # Separate XYZ
        node_sep = nodes.new('ShaderNodeSeparateXYZ')
        node_sep.parent = frame
        node_sep.location = x - 140, y - 100
        links.new(u_socket, node_sep.outputs[0])
        links.new(v_socket, node_sep.outputs[1])
        uv_socket = node_sep.inputs[0]

        x -= 180

    # UVMap node
    node_uv = nodes.new('ShaderNodeUVMap')
    node_uv.name = node_uv.label = 'UV Map Texture 0' if tex_num == 0 else 'UV Map Texture 1'
    node_uv.location = x - 160, y - 70
    node_uv.uv_map = tex['uv_map']
    links.new(uv_socket, node_uv.outputs[0])

    return node_tex


def make_simple_blender_lerp_node(mat, blender, input_map):
    # Creates a node for the blender in the simple case when it can be
    # implemented by a MixRGB (lerp) node. Returns the node if created,
    # or None if the blender wasn't simple enough.

    p, a, m, b = blender

    # It's simple if...
    is_simple = (
        # (p*a + m*(1-a))/(a + (1-a)) = lerp(m, p, a)
        b == 'One Minus A' and
        # Reading from framebuffer is not required
        p != 'Framebuffer Color' and m != 'Framebuffer Color'
    )
    if not is_simple:
        return None

    node_mix = mat.node_tree.nodes.new('ShaderNodeMixRGB')
    connect_input(mat, input_map[a], node_mix.inputs[0])
    connect_input(mat, input_map[m], node_mix.inputs[1])
    connect_input(mat, input_map[p], node_mix.inputs[2])
    input_map['Combined Color'] = node_mix.outputs[0]

    return node_mix


def get_combiner_group():
    if 'RDP Color Combiner' not in bpy.data.node_groups:
        create_combiner_group()
    return bpy.data.node_groups['RDP Color Combiner']


def create_combiner_group():
    # Creates a node group with 8 inputs and 2 outputs that performs one
    # cycle of the color combiner.
    #
    #   Output Color = (Color A - Color B) * Color C + Color D
    #   Output Alpha = (Alpha A - Alpha B) * Alpha C + Alpha D
    #
    # NOTE: The color math is currently being done in linear space,
    # should be sRGB?

    group = bpy.data.node_groups.new('RDP Color Combiner', 'ShaderNodeTree')
    nodes = group.nodes
    links = group.links

    group.inputs.new('NodeSocketColor', 'Color A')
    group.inputs.new('NodeSocketColor', 'Color B')
    group.inputs.new('NodeSocketColor', 'Color C')
    group.inputs.new('NodeSocketColor', 'Color D')
    group.inputs.new('NodeSocketFloat', 'Alpha A')
    group.inputs.new('NodeSocketFloat', 'Alpha B')
    group.inputs.new('NodeSocketFloat', 'Alpha C')
    group.inputs.new('NodeSocketFloat', 'Alpha D')
    group.outputs.new('NodeSocketColor', 'Color')
    group.outputs.new('NodeSocketFloat', 'Alpha')

    node_input = nodes.new('NodeGroupInput')
    node_subc = nodes.new('ShaderNodeMixRGB')
    node_mulc = nodes.new('ShaderNodeMixRGB')
    node_addc = nodes.new('ShaderNodeMixRGB')
    node_suba = nodes.new('ShaderNodeMath')
    node_mula = nodes.new('ShaderNodeMath')
    node_adda = nodes.new('ShaderNodeMath')
    node_output = nodes.new('NodeGroupOutput')

    node_subc.blend_type = node_suba.operation = 'SUBTRACT'
    node_mulc.blend_type = node_mula.operation = 'MULTIPLY'
    node_addc.blend_type = node_adda.operation = 'ADD'
    node_subc.inputs[0].default_value = 1.0
    node_mulc.inputs[0].default_value = 1.0
    node_addc.inputs[0].default_value = 1.0

    links.new(node_input.outputs[0], node_subc.inputs[1])
    links.new(node_input.outputs[1], node_subc.inputs[2])
    links.new(node_input.outputs[2], node_mulc.inputs[2])
    links.new(node_input.outputs[3], node_addc.inputs[2])
    links.new(node_input.outputs[4], node_suba.inputs[0])
    links.new(node_input.outputs[5], node_suba.inputs[1])
    links.new(node_input.outputs[6], node_mula.inputs[1])
    links.new(node_input.outputs[7], node_adda.inputs[1])
    links.new(node_subc.outputs[0], node_mulc.inputs[1])
    links.new(node_mulc.outputs[0], node_addc.inputs[1])
    links.new(node_suba.outputs[0], node_mula.inputs[0])
    links.new(node_mula.outputs[0], node_adda.inputs[0])
    links.new(node_addc.outputs[0], node_output.inputs[0])
    links.new(node_adda.outputs[0], node_output.inputs[1])

    node_input.location = -555, -201
    node_subc.location = -200, 219
    node_mulc.location = -15, 164
    node_addc.location = 178, 129
    node_suba.location = -150, -252
    node_mula.location = 43, -355
    node_adda.location = 247, -548
    node_output.location = 598, -113

    return group


def show_combiner_formula(a, b, c, d):
    # Formats (a-b)*c+d as a human readable string

    # sub = (a - b)
    if a == b:       sub = '0'
    elif b == '0':   sub = a
    elif a == '0':   sub = f'- {a}'
    else:            sub = f'({a} - {b})'

    # mul = sub * c
    if sub == '0':   mul = '0'
    elif c == '0':   mul = '0'
    elif sub == '1': mul = c
    elif c == '1':   mul = sub
    else:            mul = f'{sub} × {c}'

    # add = mul + d
    if mul == '0':   add = d
    elif d == '0':   add = mul
    else:            add = f'{mul} + {d}'

    return add


def show_blender_formula(p, a, m, b):
    # Formats (p*a + m*b)/(a+b) as a human readable string

    # pa = p * a
    if a == '0':     pa = '0'
    else:            pa = f'{p} × {a}'

    # mb = m * b
    if b == '0':     mb = '0'
    elif b == '1':   mb = m
    else:            mb = f'{m} × {b}'

    # num = (pa + mb)
    if pa == '0':    num = mb
    elif mb == '0':  num = pa
    else:            num = f'({pa} + {mb})'

    # den = (a + b)
    if a == '0':     den = b
    elif b == '0':   den = a
    elif b == 'One Minus A':  den = '1'
    elif (a,b) == ('0', '0'): den = '0'
    else:            den = f'({a} + {b})'

    # out = num / den
    if den == '1':   out = num
    elif num == '0': out = '0'
    elif num == den: out = '1'
    else:            out = f'{num} / {den}'

    return out


def get_texture_filter(other_mode):
    # 0 = TF_POINT    Point Sampling
    # 1 = Invalid
    # 2 = TF_AVERAGE  Box Filtering
    # 3 = TF_BILERP   Bilinear (approximated with 3 samples)
    filter = (other_mode >> 44) & 0x3
    return 'Closest' if filter == 0 else 'Linear'


def get_texture_wrap_mode(wrap):
    # bit 0 = MIRROR
    # bit 1 = CLAMP
    if wrap == 0:   return 'Repeat'
    elif wrap == 1: return 'Mirror'
    else:           return 'Clamp'


def get_combined_texture_wrap_modes(wrapS_abbr, wrapT_abbr):
    if wrapS_abbr == wrapT_abbr:
        return wrapS_abbr
    return f'{wrapS_abbr}{wrapT_abbr}'


def decode_combiner_mode(mux):
    # Decodes the u64 combiner mux value into the 16 input sources to
    # the color combiner.

    # {a,b,c,d}_** controls the a/b/c/d variable
    # *_{rgb,a}* controls the RGB/alpha equation
    # *_*{1,2} controls the 1st/2nd cycle
    a_rgb1 =  (mux >> 52) & 0xF
    c_rgb1 =  (mux >> 47) & 0x1F
    a_a1 =    (mux >> 44) & 0x7
    c_a1 =    (mux >> 41) & 0x7
    a_rgb2 =  (mux >> 37) & 0xF
    c_rgb2 =  (mux >> 32) & 0x1F
    b_rgb1 =  (mux >> 28) & 0xF
    b_rgb2 =  (mux >> 24) & 0xF
    a_a2 =    (mux >> 21) & 0x7
    c_a2 =    (mux >> 18) & 0x7
    d_rgb1 =  (mux >> 15) & 0x7
    b_a1 =    (mux >> 12) & 0x7
    d_a1 =    (mux >>  9) & 0x7
    d_rgb2 =  (mux >>  6) & 0x7
    b_a2 =    (mux >>  3) & 0x7
    d_a2 =    (mux >>  0) & 0x7

    # Convert numbers into readable strings
    rgb1 = decode_rgb_combiner_abcd(a_rgb1, b_rgb1, c_rgb1, d_rgb1)
    alpha1 = decode_alpha_combiner_abcd(a_a1, b_a1, c_a1, d_a1)
    rgb2 = decode_rgb_combiner_abcd(a_rgb2, b_rgb2, c_rgb2, d_rgb2)
    alpha2 = decode_alpha_combiner_abcd(a_a2, b_a2, c_a2, d_a2)

    return (*rgb1, *alpha1), (*rgb2, *alpha2)


def decode_rgb_combiner_abcd(a, b, c, d):
    # http://n64devkit.square7.ch/tutorial/graphics/4/image07.gif

    a = {
        0: 'Combined Color',
        1: 'Texel 0 Color',
        2: 'Texel 1 Color',
        3: 'Primitive Color',
        4: 'Shading Color',
        5: 'Environment Color',
        6: '1',
        7: 'Noise',
    }.get(a, '0')

    b = {
        0: 'Combined Color',
        1: 'Texel 0 Color',
        2: 'Texel 1 Color',
        3: 'Primitive Color',
        4: 'Shading Color',
        5: 'Environment Color',
        6: 'Key Center',
        7: 'Convert K4',
    }.get(b, '0')

    c = {
        0: 'Combined Color',
        1: 'Texel 0 Color',
        2: 'Texel 1 Color',
        3: 'Primitive Color',
        4: 'Shading Color',
        5: 'Environment Color',
        6: 'Key Scale',
        7: 'Combined Alpha',
        8: 'Texel 0 Alpha',
        9: 'Texel 1 Alpha',
        10: 'Primitive Alpha',
        11: 'Shading Alpha',
        12: 'Environment Alpha',
        13: 'LOD Fraction',
        14: 'Primitive LOD Fraction',
        15: 'Convert K5',
    }.get(c, '0')

    d = {
        0: 'Combined Color',
        1: 'Texel 0 Color',
        2: 'Texel 1 Color',
        3: 'Primitive Color',
        4: 'Shading Color',
        5: 'Environment Color',
        6: '1',
        7: '0',
    }[d]

    return a, b, c, d


def decode_alpha_combiner_abcd(a, b, c, d):
    # http://n64devkit.square7.ch/tutorial/graphics/5/image13.gif

    # a/b/d are all sourced the same way
    abd_map = {
        0: 'Combined Alpha',
        1: 'Texel 0 Alpha',
        2: 'Texel 1 Alpha',
        3: 'Primitive Alpha',
        4: 'Shading Alpha',
        5: 'Environment Alpha',
        6: '1',
        7: '0',
    }
    a = abd_map[a]
    b = abd_map[b]
    d = abd_map[d]

    c = {
        0: 'LOD Fraction',
        1: 'Texel 0 Alpha',
        2: 'Texel 1 Alpha',
        3: 'Primitive Alpha',
        4: 'Shading Alpha',
        5: 'Environment Alpha',
        6: 'Primitive LOD Fraction',
        7: '0',
    }[c]

    return a, b, c, d


def decode_blender_mode(other_mode):
    # Decodes the mux value in the other_mode state into the eight input
    # sources for the blender.

    # 1/2 means first/second cycle
    b_2 = (other_mode >> 16) & 0x3
    b_1 = (other_mode >> 18) & 0x3
    m_2 = (other_mode >> 20) & 0x3
    m_1 = (other_mode >> 22) & 0x3
    a_2 = (other_mode >> 24) & 0x3
    a_1 = (other_mode >> 26) & 0x3
    p_2 = (other_mode >> 28) & 0x3
    p_1 = (other_mode >> 30) & 0x3

    pamb1 = decode_blender_pamb(p_1, a_1, m_1, b_1)
    pamb2 = decode_blender_pamb(p_2, a_2, m_2, b_2)

    return pamb1, pamb2


def decode_blender_pamb(p, a, m, b):
    pm_map = {
        0: 'Combined Color',
        1: 'Framebuffer Color',
        2: 'Blend Color',
        3: 'Fog Color',
    }
    p = pm_map[p]
    m = pm_map[m]

    a = {
        0: 'Combined Alpha',
        1: 'Fog Alpha',
        2: 'Shading Alpha',
        3: '0',
    }[a]

    b = {
        0: f'One Minus A',
        1: 'Framebuffer Alpha',
        2: '1',
        3: '0',
    }[b]

    return p, a, m, b
