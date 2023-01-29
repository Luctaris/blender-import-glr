import sys
import io
import os
import struct
from enum import Enum

import bpy
import bmesh
from math import radians
from mathutils import Vector

class TxWrapMode(Enum):
    """
    WN: WRAP/NO CLAMP
    MN: MIRROR/NO CLAMP
    WC: WRAP/CLAMP
    MC: MIRROR/CLAMP
    NT: NOTEXTURE
    FT: FILTERED
    """
    WN_WN = 0
    WN_MN = 1
    WN_WC = 2
    WN_MC = 3
    MN_WN = 4
    MN_MN = 5
    MN_WC = 6
    MN_MC = 7
    WC_WN = 8
    WC_MN = 9
    WC_WC = 10
    WC_MC = 11
    MC_WN = 12
    MC_MN = 13
    MC_WC = 14
    MC_MC = 15
    NT_NT = 16

class SceneInfo:
    def __init__(self,
                romname,
                num_triangles,
                fog_color,
                ):
        self.romname : str = romname
        self.num_triangles : int = num_triangles
        self.num_vertices : int = (num_triangles * 3)
        self.fog_color : tuple = fog_color

class RipVertice:
    def __init__(self,
                sx, sy, sz,
                r, g, b, a,
                s0, t0, s1, t1
                ):
        self.sx : float = sx
        self.sy : float = sy
        self.sz : float = sz
        self.r : float = r
        self.g : float = g
        self.b : float = b
        self.a : float = a
        self.s0 : float = s0
        self.t0 : float = t0
        self.s1 : float = s1
        self.t1 : float = t1
    def getLocation(self):
        sx_f = float("%.6f" % self.sx)
        sy_f = float("%.6f" % self.sy)
        sz_f = float("%.6f" % self.sz)
        return (sx_f, sy_f, sz_f)
    def getVC(self, merge_alpha, inverse):
        r_f = self.r
        g_f = self.g
        b_f = self.b
        a_f = self.a
        if merge_alpha:
            r_f = float("%.6f" % (r_f * a_f))
            g_f = float("%.6f" % (g_f * a_f))
            b_f = float("%.6f" % (b_f * a_f))
        if inverse:
            r_f = abs(r_f - 1.0)
            r_f = abs(g_f - 1.0)
            r_f = abs(b_f - 1.0)
        return (r_f, g_f, b_f, 1.0)
    def getST(self, uv_map_num):
        if uv_map_num == 0:
            s_f = float("%.6f" % self.s0)
            t_f = float("%.6f" % self.t0)
        else:
            s_f = float("%.6f" % self.s1)
            t_f = float("%.6f" % self.t1)
        return (s_f, t_f)

class RipTriangle:
    def __init__(self,
                v0, v1, v2,
                prim_r, prim_g, prim_b, prim_a,
                env_r, env_g, env_b, env_a,
                blend_r, blend_g, blend_b, blend_a,
                t0_g64Crc, t1_g64Crc,
                t0_wrapmode, t1_wrapmode
                ):
        self.v0 : RipVertice = v0
        self.v1 : RipVertice = v1
        self.v2 : RipVertice = v2
        self.prim_r : float = prim_r
        self.prim_g : float = prim_g
        self.prim_b : float = prim_b
        self.prim_a : float = prim_a
        self.env_r : float = env_r
        self.env_g : float = env_g
        self.env_b : float = env_b
        self.env_a : float = env_a
        self.blend_r : float = blend_r
        self.blend_g : float = blend_g
        self.blend_b : float = blend_b
        self.blend_a : float = blend_a
        self.t0_g64Crc : int = t0_g64Crc
        self.t1_g64Crc : int = t1_g64Crc
        self.t0_wrapmode : int = t0_wrapmode
        self.t1_wrapmode : int = t1_wrapmode
    def getTC(self, color_mode, merge_alpha, inversed):
        if color_mode == 1:
            r_f = self.prim_r
            g_f = self.prim_g
            b_f = self.prim_b
            a_f = self.prim_a
        if color_mode == 2:
            r_f = self.env_r
            g_f = self.env_g
            b_f = self.env_b
            a_f = self.env_a
        if color_mode == 3:
            r_f = self.blend_r
            g_f = self.blend_g
            b_f = self.blend_b
            a_f = self.blend_a
        if merge_alpha:
            r_f = float("%.6f" % (r_f * a_f))
            g_f = float("%.6f" % (g_f * a_f))
            b_f = float("%.6f" % (b_f * a_f))
            a_f = 1.0
        if inversed:
            r_f = abs(r_f - 1.0)
            g_f = abs(g_f - 1.0)
            b_f = abs(b_f - 1.0)
            a_f = abs(a_f - 1.0)
        return (r_f, g_f, b_f, a_f)
    def getTextureName(self, texture_num):
        if texture_num == 0:
            calc_crc = self.t0_g64Crc
        else:
            calc_crc = self.t1_g64Crc
        if calc_crc == 0:
            return ""
        filename = "%016lX.png" % calc_crc
        return filename
    def getBlenderMaterialName(self):
        returning = "%016lX(%02d)" % (self.t0_g64Crc, self.t0_wrapmode)
        if self.t1_g64Crc != 0:
            returning += ":%016lX(%02d)" % (self.t1_g64Crc, self.t1_wrapmode)
        return returning
    def getT0WrapMode(self):
        return TxWrapMode(self.t0_wrapmode)
    def overrideT0WrapMode(self, new_value):
        self.t0_wrapmode = new_value
    def getT1WrapMode(self):
        return TxWrapMode(self.t1_wrapmode)
    def overrideT1WrapMode(self, new_value):
        self.t1_wrapmode = new_value

# Blender Mesh/Mat Generation Functions
def genColorMixerNode(mat_ntn, mixer_name, location):
    mat_mix_Col = mat_ntn.new("ShaderNodeMixRGB")
    mat_mix_Col.inputs[0].default_value = 1.0
    #default to white
    mat_mix_Col.inputs[1].default_value = (1.0, 1.0, 1.0, 1.0)
    mat_mix_Col.inputs[2].default_value = (1.0, 1.0, 1.0, 1.0)
    mat_mix_Col.blend_type = "MULTIPLY"
    mat_mix_Col.name = mat_mix_Col.label = mixer_name + " Mixer"
    mat_mix_Col.location = location
    return mat_mix_Col

def genColorNodes(mat_ntn, mat_ntl, color_name, location):
    mat_Col_shader = mat_ntn.new("ShaderNodeVertexColor")
    mat_Col_shader.name = mat_Col_shader.label = mat_Col_shader.layer_name = color_name
    mat_Col_shader.location = location
    mat_mix_Col = genColorMixerNode(mat_ntn, color_name, location)
    mat_mix_Col.location = ((location[0] + 215), location[1])
    mat_ntl.new(mat_Col_shader.outputs[0], mat_mix_Col.inputs[2])
    return mat_mix_Col

def createBaseMaterial(mat_name, enable_transparency, enable_culling, enable_color):
    mat = bpy.data.materials.new(mat_name)
    mat.use_nodes = True
    mat.use_backface_culling = enable_culling
    mat.shadow_method = "NONE"
    if enable_transparency:
        mat.blend_method = "HASHED"
    else:
        mat.blend_method = "OPAQUE"
    mat_ntn = mat.node_tree.nodes
    mat_ntl = mat.node_tree.links
    mat_ntn.remove(mat_ntn["Principled BSDF"])
    mat_output = mat_ntn["Material Output"]
    mat_output.location = (800,350)
    mat_emmision = mat_ntn.new("ShaderNodeEmission")
    mat_emmision.location = (350,150)
    mat_ntl.new(mat_emmision.outputs[0], mat_output.inputs[0])
    if (enable_color[0] |
        enable_color[1] |
        enable_color[2] |
        enable_color[3]) != 0:
        mat_mix_colors = genColorMixerNode(mat_ntn, "Vert", (150,250))
        mat_ntl.new(mat_mix_colors.outputs[0], mat_emmision.inputs[0])
        if enable_color[0]:
            mat_mix_VC = genColorNodes(mat_ntn, mat_ntl, "VC", (-265,75))
            mat_ntl.new(mat_mix_VC.outputs[0], mat_mix_colors.inputs[2])
        if enable_color[1]:
            mat_mix_PC = genColorNodes(mat_ntn, mat_ntl, "PC", (-265,-100))
            if enable_color[0]:
                mat_ntl.new(mat_mix_PC.outputs[0], mat_mix_VC.inputs[1])
            else:
                mat_ntl.new(mat_mix_PC.outputs[0], mat_mix_colors.inputs[2])
        if enable_color[2]:
            mat_mix_EC = genColorNodes(mat_ntn, mat_ntl, "EC", (-265,-275))
            if not mat_mix_colors.inputs[2].is_linked:
                mat_ntl.new(mat_mix_EC.outputs[0], mat_mix_colors.inputs[2])
            elif enable_color[1]:
                mat_ntl.new(mat_mix_EC.outputs[0], mat_mix_PC.inputs[1])
            else:
                mat_ntl.new(mat_mix_EC.outputs[0], mat_mix_VC.inputs[1])
        if enable_color[3]:
                mat_mix_BC = genColorNodes(mat_ntn, mat_ntl, "BC", (-265,-450))
                if not mat_mix_colors.inputs[2].is_linked:
                    mat_ntl.new(mat_mix_BC.outputs[0], mat_mix_colors.inputs[2])
                elif enable_color[2]:
                    mat_ntl.new(mat_mix_BC.outputs[0], mat_mix_EC.inputs[1])
                elif enable_color[1]:
                    mat_ntl.new(mat_mix_BC.outputs[0], mat_mix_PC.inputs[1])
                else:
                    mat_ntl.new(mat_mix_BC.outputs[0], mat_mix_VC.inputs[1])
    return mat

def loadNewImage(image_folder_path, image_filename):
    try:
        bpy.data.images.load(image_folder_path + image_filename)
    except RuntimeError:
        print("EXCEPTION: %s doesn't exist! Skipping..." % (image_folder_path + image_filename))
    return bpy.data.images.find(image_filename)

def addTxToMatIdx(mat_idx, tx_names, tx_wrapmode, abs_filepath):
    mat = bpy.data.materials[mat_idx]
    mat_ntn = mat.node_tree.nodes
    mat_ntl = mat.node_tree.links

    base_texture_idx = mat_ntn.find("Base Texture")
    detail_texture_idx = mat_ntn.find("Detail Texture")
    if detail_texture_idx != -1:
        print("ERROR: Attempted loading 2nd detail texture!\n\tmat_idx: %d, tx_wrapmode: %s, mat.name: %s" % (mat_idx, tx_wrapmode, mat.name))
        #assign to NO_TEXTURE?
        return

    new_txt_image = mat_ntn.new("ShaderNodeTexImage")

    if base_texture_idx == -1:
        img_txt_name = tx_names[0]
    else:
        img_txt_name = tx_names[1]
    
    img_txt_index = bpy.data.images.find(img_txt_name)

    if img_txt_index == -1:
        os_sep = os.path.sep
        img_txt_path = abs_filepath.rsplit(os_sep, 1)[0] + os_sep
        img_txt_index = loadNewImage(img_txt_path, img_txt_name)

    new_txt_image.image = bpy.data.images[img_txt_index]
    new_txt_uv = mat_ntn.new("ShaderNodeUVMap")

    if base_texture_idx == -1:
        new_txt_image.name = new_txt_image.label = "Base Texture"
        new_txt_image.location = (-600, 430)
        new_txt_uv.uv_map = "UV1"
        new_txt_uv.name = new_txt_uv.label = "Base UV Map"
        new_txt_uv.location = (-1685, 260)
    else:
        new_txt_image.name = new_txt_image.label = "Detail Texture"
        new_txt_image.location = (-600, -25)
        new_txt_uv.uv_map = "UV2"
        new_txt_uv.name = new_txt_uv.label = "Detail UV Map"
        new_txt_uv.location = (-1685, -190)

    # ?C_?C
    if(tx_wrapmode.value == 10 or
        tx_wrapmode.value == 11 or
        tx_wrapmode.value == 14 or
        tx_wrapmode.value == 15):
        new_txt_image.extension = "EXTEND"

    # WC_WC, WN_WN = link UV directly to image
    # !(WC_WC), !(WN_WN) = setup seperate/combine nodes
    if(tx_wrapmode.value == 0 or
        tx_wrapmode.value == 10):
        mat_ntl.new(new_txt_uv.outputs[0], new_txt_image.inputs[0])
    else:
        new_seperate_xyz = mat_ntn.new("ShaderNodeSeparateXYZ")
        new_combine_xyz = mat_ntn.new("ShaderNodeCombineXYZ")
        mat_ntl.new(new_txt_uv.outputs[0], new_seperate_xyz.inputs[0])
        mat_ntl.new(new_combine_xyz.outputs[0], new_txt_image.inputs[0])
        mat_ntl.new(new_seperate_xyz.outputs[2], new_combine_xyz.inputs[2])
        if base_texture_idx == -1:
            new_seperate_xyz.location = (-1485, 275)
            new_combine_xyz.location = (-785, 275)
        else:
            new_seperate_xyz.location = (-1485, -175)
            new_combine_xyz.location = (-785, -175)

    # ?C_?N
    if(tx_wrapmode.value == 8 or
        tx_wrapmode.value == 9 or
        tx_wrapmode.value == 12 or
        tx_wrapmode.value == 13):
        new_clamp_x = mat_ntn.new("ShaderNodeClamp")
        mat_ntl.new(new_seperate_xyz.outputs[0], new_clamp_x.inputs[0])
        if base_texture_idx == -1:
            new_clamp_x.location = (-1250, 475)
        else:
            new_clamp_x.location = (-1250, 25)

    # ?N_?C
    if(tx_wrapmode.value == 2 or
        tx_wrapmode.value == 3 or
        tx_wrapmode.value == 6 or
        tx_wrapmode.value == 7):
        new_clamp_y = mat_ntn.new("ShaderNodeClamp")
        mat_ntl.new(new_seperate_xyz.outputs[1], new_clamp_y.inputs[0])
        if base_texture_idx == -1:
            new_clamp_y.location = (-1250, 310)
        else:
            new_clamp_y.location = (-1250, -140)

    # WC_??
    if(tx_wrapmode.value == 8 or
        tx_wrapmode.value == 9):
        mat_ntl.new(new_clamp_x.outputs[0], new_combine_xyz.inputs[0])

    # ??_WC
    if(tx_wrapmode.value == 2 or
        tx_wrapmode.value == 6):
        mat_ntl.new(new_clamp_y.outputs[0], new_combine_xyz.inputs[1])

    # M?_??
    if(tx_wrapmode.value == 4 or
        tx_wrapmode.value == 5 or
        tx_wrapmode.value == 6 or
        tx_wrapmode.value == 7 or
        tx_wrapmode.value == 12 or
        tx_wrapmode.value == 13 or
        tx_wrapmode.value == 14 or
        tx_wrapmode.value == 15):
        new_mirror_x = mat_ntn.new("ShaderNodeMath")
        new_mirror_x.operation = "PINGPONG"
        new_mirror_x.inputs[1].default_value = 1.0
        if base_texture_idx == -1:
            new_mirror_x.location = (-1030, 475)
        else:
            new_mirror_x.location = (-1030, 25)

    # ??_M?
    if(tx_wrapmode.value % 2 == 1):
        #all odd values
        new_mirror_y = mat_ntn.new("ShaderNodeMath")
        new_mirror_y.operation = "PINGPONG"
        new_mirror_y.inputs[1].default_value = 1.0
        if base_texture_idx == -1:
            new_mirror_y.location = (-1030, 310)
        else:
            new_mirror_y.location = (-1030, -140)

    # MN_??
    if(tx_wrapmode.value == 4 or
        tx_wrapmode.value == 5 or
        tx_wrapmode.value == 6 or
        tx_wrapmode.value == 7):
        mat_ntl.new(new_seperate_xyz.outputs[0], new_mirror_x.inputs[0])
        mat_ntl.new(new_mirror_x.outputs[0], new_combine_xyz.inputs[0])

    # MC_??
    if(tx_wrapmode.value == 12 or
        tx_wrapmode.value == 13 or
        tx_wrapmode.value == 14 or
        tx_wrapmode.value == 15):
        mat_ntl.new(new_seperate_xyz.outputs[0], new_mirror_x.inputs[0])
        mat_ntl.new(new_mirror_x.outputs[0], new_combine_xyz.inputs[0])

    # ??_MN
    if(tx_wrapmode.value == 1 or
        tx_wrapmode.value == 5 or
        tx_wrapmode.value == 9 or
        tx_wrapmode.value == 13):
        mat_ntl.new(new_seperate_xyz.outputs[1], new_mirror_y.inputs[0])
        mat_ntl.new(new_mirror_y.outputs[0], new_combine_xyz.inputs[1])

    # Misc cleanup
    if(tx_wrapmode.value == 1 or
        tx_wrapmode.value == 2 or
        tx_wrapmode.value == 3 or
        tx_wrapmode.value == 11):
        mat_ntl.new(new_seperate_xyz.outputs[0], new_combine_xyz.inputs[0])

    if(tx_wrapmode.value == 4 or
        tx_wrapmode.value == 8 or
        tx_wrapmode.value == 12 or
        tx_wrapmode.value == 14):
        mat_ntl.new(new_seperate_xyz.outputs[1], new_combine_xyz.inputs[1])

    if(tx_wrapmode.value == 12 or
        tx_wrapmode.value == 13):
        mat_ntl.new(new_clamp_x.outputs[0], new_mirror_x.inputs[0])

    if(tx_wrapmode.value == 3 or
        tx_wrapmode.value == 7):
        mat_ntl.new(new_clamp_y.outputs[0], new_mirror_y.inputs[0])

    if(tx_wrapmode.value == 3 or
        tx_wrapmode.value == 7 or
        tx_wrapmode.value == 11 or
        tx_wrapmode.value == 15):
        mat_ntl.new(new_mirror_y.outputs[0], new_combine_xyz.inputs[1])

    if(tx_wrapmode.value == 11 or
        tx_wrapmode.value == 15):
        mat_ntl.new(new_seperate_xyz.outputs[1], new_mirror_y.inputs[0])

    mat_mix_colors_idx = mat_ntn.find("Vert Mixer")

    if base_texture_idx == -1:
        new_transparent_bsdf = mat_ntn.new("ShaderNodeBsdfTransparent")
        new_transparent_bsdf.location = (350,250)
        new_mix_shader = mat_ntn.new("ShaderNodeMixShader")
        new_mix_shader.location = (575,350)
        if mat_mix_colors_idx != -1:
            mat_ntl.new(new_txt_image.outputs[0], mat_ntn[mat_mix_colors_idx].inputs[1])
        else:
            mat_ntl.new(new_txt_image.outputs[0], mat_ntn["Emission"].inputs[0])
        mat_ntl.new(new_txt_image.outputs[1], new_mix_shader.inputs[0])
        mat_ntl.new(mat_ntn["Emission"].outputs[0], new_mix_shader.inputs[2])
        mat_ntl.new(new_transparent_bsdf.outputs[0], new_mix_shader.inputs[1])
        mat_ntl.new(new_mix_shader.outputs[0], mat_ntn["Material Output"].inputs[0])
    else:
        new_alpha_mixer = mat_ntn.new("ShaderNodeMixRGB")
        new_alpha_mixer.inputs[0].default_value = 0.5
        new_alpha_mixer.blend_type = "MIX"
        new_alpha_mixer.name = new_alpha_mixer.label = "Alpha Mixer"
        new_alpha_mixer.location = (-265,430)
        new_detail_mixer = mat_ntn.new("ShaderNodeMixRGB")
        new_detail_mixer.inputs[0].default_value = 0.5
        new_detail_mixer.blend_type = "MIX"
        new_detail_mixer.name = new_detail_mixer.label = "Base + Detail Mixer"
        new_detail_mixer.location = (-265,250)
        mat_ntl.new(new_txt_image.outputs[1], new_alpha_mixer.inputs[2])
        mat_ntl.new(new_alpha_mixer.outputs[0], mat_ntn["Mix Shader"].inputs[0])
        mat_ntl.new(mat_ntn["Base Texture"].outputs[0], new_detail_mixer.inputs[1])
        mat_ntl.new(mat_ntn["Base Texture"].outputs[1], new_alpha_mixer.inputs[1])
        if mat_mix_colors_idx != -1:
            mat_ntl.new(new_detail_mixer.outputs[0], mat_ntn[mat_mix_colors_idx].inputs[1])
        else:
            mat_ntl.new(new_detail_mixer.outputs[0], mat_ntn["Emission"].inputs[0])
        mat_ntl.new(new_txt_image.outputs[0], new_detail_mixer.inputs[2])

def genBpyObjMesh(context, file_data, bpy_data_lists, curr_glr_filepath, filename_no_ext, **keywords):
    #unpacking args
    scene_data = file_data[0]
    tri_data = file_data[1]
    glr_vertice_data = bpy_data_lists[0]
    glr_face_layout_data = bpy_data_lists[1]
    glr_vertice_UV1_data = bpy_data_lists[2]
    glr_vertice_UV2_data = bpy_data_lists[3]
    glr_vertice_VC_data = bpy_data_lists[4]
    glr_triangle_PC_data = bpy_data_lists[5]
    glr_triangle_EC_data = bpy_data_lists[6]
    glr_triangle_BC_data = bpy_data_lists[7]
    glr_vertice_CMBC_data = bpy_data_lists[8]
    glr_triangle_tx_data = bpy_data_lists[9]
    #packing commonly used vars
    glr_color_enable = \
    (
        keywords["VC_enable"][0],
        keywords["PC_enable"][0],
        keywords["EC_enable"][0],
        keywords["BC_enable"][0],
        keywords["merge_channels"]
    )
    glr_triangle_wrapmode_override = \
    (
        TxWrapMode[keywords["WN_WN_override"]].value,
        TxWrapMode[keywords["WN_MN_override"]].value,
        TxWrapMode[keywords["WN_WC_override"]].value,
        TxWrapMode[keywords["WN_MC_override"]].value,
        TxWrapMode[keywords["MN_WN_override"]].value,
        TxWrapMode[keywords["MN_MN_override"]].value,
        TxWrapMode[keywords["MN_WC_override"]].value,
        TxWrapMode[keywords["MN_MC_override"]].value,
        TxWrapMode[keywords["WC_WN_override"]].value,
        TxWrapMode[keywords["WC_MN_override"]].value,
        TxWrapMode[keywords["WC_WC_override"]].value,
        TxWrapMode[keywords["WC_MC_override"]].value,
        TxWrapMode[keywords["MC_WN_override"]].value,
        TxWrapMode[keywords["MC_MN_override"]].value,
        TxWrapMode[keywords["MC_WC_override"]].value,
        TxWrapMode[keywords["MC_MC_override"]].value,
        16 # NT_NT, should never be used
    )
    glr_color_channel_count = 0
    for col in glr_color_enable[:-1]:
        if col is True:
            glr_color_channel_count += 1
    #Creating the mesh
    glr_obj_mesh_prefix = scene_data.romname + '_' + filename_no_ext
    glr_mesh = bpy.data.meshes.new(glr_obj_mesh_prefix + "_mesh")
    glr_mesh.from_pydata(glr_vertice_data, [], glr_face_layout_data)
    glr_obj = bpy.data.objects.new(glr_obj_mesh_prefix, glr_mesh)
    context.scene.collection.objects.link(glr_obj)
    #Adding the color attributes
    glr_mesh_VC = glr_mesh_PC = glr_mesh_EC = glr_mesh_BC = glr_mesh_CMBC = None
    if glr_color_enable[0]:
        null_print = glr_obj.data.vertex_colors.new(name="VC")
    if glr_color_enable[1]:
        null_print = glr_obj.data.vertex_colors.new(name="PC")
    if glr_color_enable[2]:
        null_print = glr_obj.data.vertex_colors.new(name="EC")
    if glr_color_enable[3]:
        null_print = glr_obj.data.vertex_colors.new(name="BC")
    if glr_color_enable[4]:
        if((glr_color_enable[0] |
        glr_color_enable[1] |
        glr_color_enable[2] |
        glr_color_enable[3]) != 0 and
        glr_color_channel_count > 1):
            null_print = glr_obj.data.vertex_colors.new(name="CMBC")
        else:
            print("INFO: Combine Color Channels option was set, but either 0 or only 1 color channel was chosen. Skipping CMBC creation...")
    #Adding the UV maps
    null_print = glr_obj.data.uv_layers.new(name="UV1")
    null_print = glr_obj.data.uv_layers.new(name="UV2")
    #Creating holders
    if glr_color_enable[0]:
        glr_mesh_VC = glr_obj.data.vertex_colors["VC"]
    if glr_color_enable[1]:
        glr_mesh_PC = glr_obj.data.vertex_colors["PC"]
    if glr_color_enable[2]:
        glr_mesh_EC = glr_obj.data.vertex_colors["EC"]
    if glr_color_enable[3]:
        glr_mesh_BC = glr_obj.data.vertex_colors["BC"]
    if glr_obj.data.vertex_colors.find("CMBC") != -1:
        glr_mesh_CMBC = glr_obj.data.vertex_colors["CMBC"]
    glr_mesh_UV1 = glr_obj.data.uv_layers["UV1"]
    glr_mesh_UV2 = glr_obj.data.uv_layers["UV2"]
    #Applying UV + Col vals to verts
    for i in range(scene_data.num_vertices):
        glr_mesh_UV1.data[i].uv = glr_vertice_UV1_data[i]
        glr_mesh_UV2.data[i].uv = glr_vertice_UV2_data[i]
        if glr_color_enable[0]:
            glr_mesh_VC.data[i].color = glr_vertice_VC_data[i]
        if glr_color_enable[1]:
            glr_mesh_PC.data[i].color = glr_triangle_PC_data[i]
        if glr_color_enable[2]:
            glr_mesh_EC.data[i].color = glr_triangle_EC_data[i]
        if glr_color_enable[3]:
            glr_mesh_BC.data[i].color = glr_triangle_BC_data[i]
        if glr_obj.data.vertex_colors.find("CMBC") != -1:
            glr_mesh_CMBC.data[i].color = glr_vertice_CMBC_data[i]
    #Applying textures to faces
    for i in range(scene_data.num_triangles):
        tx0_filename = glr_triangle_tx_data[i][0]
        tx1_filename = glr_triangle_tx_data[i][1]
        tx_names = (tx0_filename, tx1_filename)
        num_used_textures = 0
        if tx0_filename != "":
            num_used_textures += 1
        if tx1_filename != "":
            num_used_textures += 1
        if tx0_filename == "" and tx1_filename != "":
            print("EXCEPTION: Invalid base texture, valid detail texture found. Assigning to NO_TEXURE...")
            num_used_textures = 0
        if num_used_textures == 0:
            no_mat_global_idx = bpy.data.materials.find("NO_TEXTURE")
            no_mat_idx = glr_mesh.materials.find("NO_TEXTURE")
            if no_mat_global_idx == -1:
                NT_mat = createBaseMaterial("NO_TEXTURE",
                                            keywords["enable_mat_transparency"],
                                            keywords["enable_bf_culling"],
                                            glr_color_enable)
                glr_mesh.materials.append(NT_mat)
            else:
                if no_mat_idx == -1:
                    glr_mesh.materials.append(bpy.data.materials[no_mat_global_idx])
            glr_mesh.polygons[i].material_index = glr_mesh.materials.find("NO_TEXTURE")
        else:

            """
            # after mat_name = tri_data[i].getBlenderMaterialName()
            mat_idx = glr_mesh.materials.find(mat_name)
            if mat_idx == -1:
                new_mat = createBaseMaterial(mat_name,
                                            keywords["enable_mat_transparency"],
                                            keywords["enable_bf_culling"],
                                            glr_color_enable)
                glr_mesh.materials.append(new_mat)
                new_mat_idx = bpy.data.materials.find(mat_name)
                addTxToMatIdx(new_mat_idx, tx_names, tri_data[i].getT0WrapMode(), curr_glr_filepath)
                glr_mesh.polygons[i].material_index = glr_mesh.materials.find(mat_name)
                mat_idx = glr_mesh.polygons[i].material_index
            else:
                glr_mesh.polygons[i].material_index = mat_idx
            data_mat_idx = bpy.data.materials.find(mat_name)
            mat_dtn = bpy.data.materials[data_mat_idx].node_tree.nodes.find("Detail Texture")
            if num_used_textures == 2 and mat_dtn == -1:
                addTxToMatIdx(data_mat_idx, tx_names, tri_data[i].getT1WrapMode(), curr_glr_filepath)
    return glr_obj
    """

            #wrapmode material override happens here
            overridden_T0_wm = glr_triangle_wrapmode_override[tri_data[i].getT0WrapMode().value]
            overridden_T1_wm = glr_triangle_wrapmode_override[tri_data[i].getT1WrapMode().value]
            tri_data[i].overrideT0WrapMode(overridden_T0_wm)
            tri_data[i].overrideT1WrapMode(overridden_T1_wm)
            mat_name = tri_data[i].getBlenderMaterialName()
            mat_global_idx = bpy.data.materials.find(mat_name)
            mat_idx = glr_mesh.materials.find(mat_name)
            if mat_global_idx == -1:
                new_mat = createBaseMaterial(mat_name,
                                            keywords["enable_mat_transparency"],
                                            keywords["enable_bf_culling"],
                                            glr_color_enable)
                glr_mesh.materials.append(new_mat)
                new_mat_idx = bpy.data.materials.find(mat_name)
                addTxToMatIdx(new_mat_idx, tx_names, tri_data[i].getT0WrapMode(), curr_glr_filepath)
            else:
                if mat_idx == -1:
                    glr_mesh.materials.append(bpy.data.materials[mat_global_idx])

            glr_mesh.polygons[i].material_index = glr_mesh.materials.find(mat_name)
            mat_idx = glr_mesh.polygons[i].material_index
            glr_mesh.polygons[i].material_index = mat_idx
            mat_global_idx = bpy.data.materials.find(mat_name)
            mat_dtn = bpy.data.materials[mat_global_idx].node_tree.nodes.find("Detail Texture")
            if num_used_textures == 2 and mat_dtn == -1:
                addTxToMatIdx(mat_global_idx, tx_names, tri_data[i].getT1WrapMode(), curr_glr_filepath)
    return glr_obj

def performObjTransformations(glr_obj, transform_vectors, perform_merge_triangles):
    curr_location = glr_obj.location
    glr_obj.location = curr_location + transform_vectors[0]
    glr_obj.rotation_euler = transform_vectors[1]
    glr_obj.scale = transform_vectors[2]
    if perform_merge_triangles:
        glr_obj_mesh = glr_obj.data
        bm = bmesh.new()
        bm.from_mesh(glr_obj_mesh)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)
        bm.to_mesh(glr_obj_mesh)
        bm.free()

def genFogBoundingBox(context, glr_obj, fog_color):
    glr_mesh = glr_obj.data
    if fog_color == (0.0, 0.0, 0.0, 1.0):
        print("INFO: Fog color is pure black/null (0.0, 0.0, 0.0, 1.0), skipping creation...")
        return
    cube_verts = [None] * 8
    glr_obj_matrix = glr_obj.matrix_world
    cube_face_layout = \
                    (
                        (0, 1, 2, 3),
                        (5, 4, 7, 6),
                        (4, 0, 3, 7),
                        (1, 5, 6, 2),
                        (6, 7, 3, 2),
                        (5, 1, 0, 4)
                    )
    for i in range(8):
        cube_verts[i] = glr_obj_matrix @ Vector(glr_obj.bound_box[i])
    glr_fog_mesh = bpy.data.meshes.new(glr_mesh.name + "_fog")
    glr_fog_mesh.from_pydata(cube_verts, [], cube_face_layout)
    new_fog_mat = bpy.data.materials.new(glr_obj.name + "fog")
    new_fog_mat.use_nodes = True
    new_fog_mat_ntn = new_fog_mat.node_tree.nodes
    new_fog_mat_ntn.remove(new_fog_mat_ntn["Principled BSDF"])
    mat_output = new_fog_mat_ntn["Material Output"]
    mat_output.location = (800,350)
    new_volume = new_fog_mat_ntn.new("ShaderNodeVolumePrincipled")
    new_volume.inputs[0].default_value = fog_color
    new_volume.inputs[2].default_value = 0.0075
    new_volume.location = (450, 350)
    new_fog_mat.node_tree.links.new(new_volume.outputs[0], mat_output.inputs[1])
    glr_fog_obj = bpy.data.objects.new(glr_obj.name + "_fog", glr_fog_mesh)
    glr_fog_obj.parent = glr_obj
    glr_fog_obj.display_type = 'WIRE'
    context.scene.collection.objects.link(glr_fog_obj)
    glr_fog_obj.data.materials.append(new_fog_mat)
    
### Blender Data Generation Functions
def genVertexList(tri_info):
    num_tris = tri_info[0]
    num_vertices = tri_info[1]
    tri_data = tri_info[2]
    vertices = list([None]) * num_vertices
    vtxCounter = 0
    for i in range(num_tris):
        vertices[vtxCounter] = tri_data[i].v0.getLocation()
        vertices[vtxCounter+1] = tri_data[i].v1.getLocation()
        vertices[vtxCounter+2] = tri_data[i].v2.getLocation()
        vtxCounter += 3
    return vertices

def genFaceMapList(num_tris):
    vtxCounter0 = 0
    vtxCounter1 = 1
    vtxCounter2 = 2
    face_list = list([None]) * num_tris
    for i in range(num_tris):
        face_list[i] = (vtxCounter0, vtxCounter1, vtxCounter2)
        vtxCounter0 += 3
        vtxCounter1 += 3
        vtxCounter2 += 3
    return face_list

def genUVMapList(tri_info, uv_map_num):
    num_tris = tri_info[0]
    num_vertices = tri_info[1]
    tri_data = tri_info[2]
    st_data = list([None]) * num_vertices
    vtxCounter = 0
    for i in range(num_tris):
        st_data[vtxCounter] = tri_data[i].v0.getST(uv_map_num)
        st_data[vtxCounter+1] = tri_data[i].v1.getST(uv_map_num)
        st_data[vtxCounter+2] = tri_data[i].v2.getST(uv_map_num)
        vtxCounter += 3
    return st_data

def genVCList(color_fmt_data, inverse):
    num_tris = color_fmt_data[0][0]
    num_vertices = color_fmt_data[0][1]
    tri_data = color_fmt_data[0][2]
    merge_alpha = color_fmt_data[1]
    vc_vertices = list([None]) * num_vertices
    vtxCounter = 0
    for i in range(num_tris):
        vc_vertices[vtxCounter] = tri_data[i].v0.getVC(merge_alpha, inverse)
        vc_vertices[vtxCounter+1] = tri_data[i].v1.getVC(merge_alpha, inverse)
        vc_vertices[vtxCounter+2] = tri_data[i].v2.getVC(merge_alpha, inverse)
        vtxCounter += 3
    return vc_vertices

def genTCList(color_fmt_data, color_mode, inverse):
    num_tris = color_fmt_data[0][0]
    num_vertices = color_fmt_data[0][1]
    tri_data = color_fmt_data[0][2]
    merge_alpha = color_fmt_data[1]
    tc_vertices = list([None]) * num_vertices
    vtxCounter = 0
    for i in range(num_tris):
        tc_color_data = tri_data[i].getTC(color_mode, merge_alpha, inverse)
        tc_vertices[vtxCounter] = tc_color_data
        tc_vertices[vtxCounter+1] = tc_color_data
        tc_vertices[vtxCounter+2] = tc_color_data
        vtxCounter += 3
    return tc_vertices

def genDefaultVertList(num_vertices):
    default_vertices = list([None]) * num_vertices
    for i in range(num_vertices):
        default_vertices[i] = (1.0, 1.0, 1.0, 1.0)
    return default_vertices

def getCMBCVert(VC_vert, PC_vert, EC_vert, BC_vert):
    r_f = float("%.6f" % (VC_vert[0] * PC_vert[0] * EC_vert[0] * BC_vert[0]))
    g_f = float("%.6f" % (VC_vert[1] * PC_vert[1] * EC_vert[1] * BC_vert[1]))
    b_f = float("%.6f" % (VC_vert[2] * PC_vert[2] * EC_vert[2] * BC_vert[2]))
    return (r_f, g_f, b_f, 1.0)

def genCMBCList(num_vertices, VC_list, PC_list, EC_list, BC_list):
    cmbc_vertices = list([None]) * num_vertices
    for i in range(num_vertices):
        cmbc_vertices[i] = getCMBCVert(VC_list[i], PC_list[i], EC_list[i], BC_list[i])
    return cmbc_vertices

def genTxList(num_tris, tri_data):
    tx_tris = list([None]) * num_tris
    for i in range(num_tris):
        tx0_filename = tri_data[i].getTextureName(0)
        tx1_filename = tri_data[i].getTextureName(1)
        tx_tris[i] = [tx0_filename, tx1_filename]
    return tx_tris

def genBpyDataLists(file_data, color_kws, filter_kws):
    scene_data = file_data[0]
    tri_data = file_data[1]
    #filtering out tris
    deleting_idxs = []
    for i in range(scene_data.num_triangles):
        if tri_data[i].t0_g64Crc == 0:
            if filter_kws[2]:
                deleting_idxs.append(i)
                continue
            else:
                continue
        if filter_kws[0]:
            if tri_data[i].getTextureName(0)[:-4] in filter_kws[1]:
                deleting_idxs.append(i)
        else:
            if tri_data[i].getTextureName(0)[:-4] not in filter_kws[1]:
                deleting_idxs.append(i)
    deleting_idxs.reverse()
    for i in range(len(deleting_idxs)):
        del tri_data[deleting_idxs[i]]
    del deleting_idxs
    scene_data.num_triangles = len(tri_data)
    scene_data.num_vertices = scene_data.num_triangles * 3
    tri_info = (scene_data.num_triangles, scene_data.num_vertices, tri_data)
    # Blender Triangle Gen
    glr_vertice_data = genVertexList(tri_info)
    glr_face_layout_data = genFaceMapList(scene_data.num_triangles)
    # UV Map Data Gen
    glr_vertice_UV1_data = genUVMapList(tri_info, 0)
    glr_vertice_UV2_data = genUVMapList(tri_info, 1)
    # Color Data Gen
    glr_vertice_VC_data =\
    glr_triangle_PC_data =\
    glr_triangle_EC_data =\
    glr_triangle_BC_data =\
    glr_triangle_CMBC_data = None
    color_fmt_data = (tri_info, color_kws[0])
    if color_kws[1][0]:
        glr_vertice_VC_data = genVCList(color_fmt_data, color_kws[1][1])
    if color_kws[2][0]:
        glr_triangle_PC_data = genTCList(color_fmt_data, 1, color_kws[2][1])
    if color_kws[3][0]: 
        glr_triangle_EC_data = genTCList(color_fmt_data, 2, color_kws[3][1])
    if color_kws[4][0]:
        glr_triangle_BC_data = genTCList(color_fmt_data, 3, color_kws[4][1])
    if(color_kws[5] and
        color_kws[1][0] |
        color_kws[2][0] |
        color_kws[3][0] |
        color_kws[4][0]) != 0:
        if glr_vertice_VC_data is None:
            glr_vertice_VC_data = genDefaultVertList(tri_info[1])
        if glr_triangle_PC_data is None:
            glr_triangle_PC_data = genDefaultVertList(tri_info[1])
        if glr_triangle_EC_data is None:
            glr_triangle_EC_data = genDefaultVertList(tri_info[1])
        if glr_triangle_BC_data is None:
            glr_triangle_BC_data = genDefaultVertList(tri_info[1])
        glr_triangle_CMBC_data = genCMBCList(scene_data.num_vertices,
                                            glr_vertice_VC_data,
                                            glr_triangle_PC_data,
                                            glr_triangle_EC_data,
                                            glr_triangle_BC_data)
    # Texture Data Map Gen
    glr_triangle_tx_data = genTxList(scene_data.num_triangles, tri_data)
    return (glr_vertice_data,
            glr_face_layout_data,
            glr_vertice_UV1_data,
            glr_vertice_UV2_data,
            glr_vertice_VC_data,
            glr_triangle_PC_data,
            glr_triangle_EC_data,
            glr_triangle_BC_data,
            glr_triangle_CMBC_data,
            glr_triangle_tx_data)
###

### File Parsing Functions
def parse_tris(num_tris, fb):
    tri_data = [None] * num_tris
    for i in range(num_tris):
        (
            # RipVertice[3] (33f)
            v0_sx, v0_sy, v0_sz,
            v0_r, v0_g, v0_b, v0_a,
            v0_s0, v0_t0, v0_s1, v0_t1,
            v1_sx, v1_sy, v1_sz,
            v1_r, v1_g, v1_b, v1_a,
            v1_s0, v1_t0, v1_s1, v1_t1,
            v2_sx, v2_sy, v2_sz,
            v2_r, v2_g, v2_b, v2_a,
            v2_s0, v2_t0, v2_s1, v2_t1,
            # Rip Vertice[3] end (at 132)
            __PAD0,                     # 1I
            t_p_r, t_p_g, t_p_b, t_p_a, #
            t_e_r, t_e_g, t_e_b, t_e_a, #
            t_b_r, t_b_g, t_b_b, t_b_a, # 12f
            t_t0_g64Crc, t_t1_g64Crc,   # 2Q
            t_t0_wm, t_t1_wm,           # 2B
            __PAD1,                     # 1H
            __PAD2                      # 1I
        ) = struct.unpack("<33f1I12f2Q2B1H1I",fb.read(208))

        # combine everything
        v0 = RipVertice(v0_sx, v0_sy, v0_sz,
                        v0_r, v0_g, v0_b, v0_a,
                        v0_s0, v0_t0,
                        v0_s1, v0_t1)
        v1 = RipVertice(v1_sx, v1_sy, v1_sz,
                        v1_r, v1_g, v1_b, v1_a,
                        v1_s0, v1_t0,
                        v1_s1, v1_t1)
        v2 = RipVertice(v2_sx, v2_sy, v2_sz,
                        v2_r, v2_g, v2_b, v2_a,
                        v2_s0, v2_t0,
                        v2_s1, v2_t1)
        rt = RipTriangle(v0, v1, v2,
                        t_p_r, t_p_g, t_p_b, t_p_a,
                        t_e_r, t_e_g, t_e_b, t_e_a,
                        t_b_r, t_b_g, t_b_b, t_b_a,
                        t_t0_g64Crc,
                        t_t1_g64Crc,
                        t_t0_wm, t_t1_wm)
        tri_data[i] = rt
    fb.close()
    return tri_data

def parse_file(curr_glr_filepath):
    with io.open(curr_glr_filepath, 'rb') as fb:
        if fb.read(6) != b'GL64R\0':
            raise RuntimeError("Not a valid N64 scene rip file")
        version = struct.unpack("<H", fb.read(2))
        if version[0] != 1:
            raise RuntimeError("Unknown N64 Ripper version (%d) encountered" % version)
        romname_raw = fb.read(20)
        if romname_raw[0] == 0x00:
            raise RuntimeError("Empty rom name encountered")
        try:
            romname_raw = romname_raw[:romname_raw.index(0x00)]
        except ValueError:
            #no null char found, using all 20 available chars
            pass
        romname = romname_raw.decode()
        num_tris = struct.unpack("<I", fb.read(4))
        if num_tris[0] == 0:
            raise RuntimeError("File triangle count is 0")
        num_vertices = num_tris[0] * 3
        (fog_r, fog_g, fog_b) = struct.unpack("<3f", fb.read(12))
        fog_color = (fog_r, fog_g, fog_b, 1.0)
        calc_left = 208 * num_tris[0] # sizeof(RipTriangle): 208
        to_scan = os.path.getsize(curr_glr_filepath) - 44 #sizeof(RipHeader): 44
        if to_scan != calc_left:
            raise RuntimeError("Expected %d remaining bytes, found %d left" % (calc_left, to_scan))
        scene_data = SceneInfo(romname, num_tris[0], fog_color)
        tri_data = parse_tris(num_tris[0], fb)
    return (scene_data, tri_data)
###

def load_glr(context, curr_glr_filepath, filename_no_ext, **keywords):
    file_data = parse_file(curr_glr_filepath)
    if bpy.data.objects.find(file_data[0].romname + '_' + filename_no_ext) != -1:
        raise RuntimeError("%s is already loaded! Aborting import..." % (filename_no_ext + ".glr"))
    bpy_color_kws = \
        (
            keywords["merge_alpha"],
            keywords["VC_enable"],
            keywords["PC_enable"],
            keywords["EC_enable"],
            keywords["BC_enable"],
            keywords["merge_channels"]
        )
    bpy_filter_kws = \
        (
            keywords["filter_mode"],
            keywords["filter_options"].split(','),
            keywords["remove_no_textures"]
        )
    bpy_data_lists = genBpyDataLists(file_data, bpy_color_kws, bpy_filter_kws)
    glr_obj = genBpyObjMesh(context, file_data, bpy_data_lists, curr_glr_filepath, filename_no_ext, **keywords)
    transform_vectors = \
    (
        keywords["move"],
        keywords["rotation"],
        keywords["scale"],
    )
    performObjTransformations(glr_obj, transform_vectors, keywords["merge_doubles"])
    if keywords["fog_enable"]:
        genFogBoundingBox(context, glr_obj, file_data[0].fog_color)
    if keywords["enable_srgb"]:
        bpy.context.scene.display_settings.display_device = "sRGB"
        bpy.context.scene.view_settings.view_transform = "Standard"
        bpy.context.scene.sequencer_colorspace_settings.name = "sRGB"
    

### Import Plugin Entry Point
def load(context, **keywords):
    dir_name = os.path.dirname(keywords["filepath"])
    found_glr = False
    for glr_file in keywords["files"]:
        if glr_file.name[-4:] == ".glr":
            found_glr = True
    if found_glr == False:
        raise RuntimeError("No .glr files have been selected for import!")
    for glr_file in keywords["files"]:
        abs_filepath = os.path.join(dir_name, glr_file.name)
        if(glr_file.name[-4:]) != ".glr":
            print("INFO: %s is not a .glr file! Skipping..." % abs_filepath)
            continue
        load_glr(context, abs_filepath, glr_file.name[:-4], **keywords)
    return {'FINISHED'}
###