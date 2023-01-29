bl_info = {
    "name": "GLideN64 Rip (GLR) Importer",
    "author": "Luctaris",
    "version": (1, 0, 0),
    "blender": (2, 80, 0),
    "location": "File > Import",
    "description": "Import GLR",
    "warning": "",
    "doc_url": "https://github.com/Luctaris/GLideN64/wiki",
    "tracker_url": "https://github.com/Luctaris/GLideN64/issues",
    "category": "Import-Export",
}

if "bpy" in locals():
    import importlib
    if "import_glr" in locals():
        importlib.reload(import_glr)

import os
from math import radians
import bpy
import bmesh
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty, BoolProperty, BoolVectorProperty, EnumProperty, FloatVectorProperty, CollectionProperty
from bpy.types import Operator, Panel, OperatorFileListElement

WM_ENUMS = (
        ("WN_WN", "WN_WN (0)", "Wrap No-Clamp / Wrap No-Clamp"),
        ("WN_MN", "WN_MN (1)", "Wrap No-Clamp / Mirror No-Clamp"),
        ("WN_WC", "WN_WC (2)", "Wrap No-Clamp / Wrap Clamp"),
        ("WN_MC", "WN_MC (3)", "Wrap No-Clamp / Mirror Clamp"),
        ("MN_WN", "MN_WN (4)", "Mirror No-Clamp / Wrap No-Clamp"),
        ("MN_MN", "MN_MN (5)", "Mirror No-Clamp / Mirror No-Clamp"),
        ("MN_WC", "MN_WC (6)", "Mirror No-Clamp / Wrap Clamp"),
        ("MN_MC", "MN_MC (7)", "Mirror No-Clamp / Mirror Clamp"),
        ("WC_WN", "WC_WN (8)", "Wrap Clamp / Wrap No-Clamp"),
        ("WC_MN", "WC_MN (9)", "Wrap Clamp / Mirror No-Clamp"),
        ("WC_WC", "WC_WC (10)", "Wrap Clamp / Wrap Clamp"),
        ("WC_MC", "WC_MC (11)", "Wrap Clamp / Mirror Clamp"),
        ("MC_WN", "MC_WN (12)", "Mirror Clamp / Wrap No-Clamp"),
        ("MC_MN", "MC_MN (13)", "Mirror Clamp / Mirror No-Clamp"),
        ("MC_WC", "MC_WC (14)", "Mirror Clamp / Wrap Clamp"),
        ("MC_MC", "MC_MC (15)", "Mirror Clamp / Mirror Clamp"),
)

class GLR_OT_FilterHelper_TextureList(Operator):
    """Generates a list of selected materials in edit mode"""
    bl_idname = "import_glr.gen_filter_list"
    bl_label = "Generate Texture Filter List"

    def scan_polygons(self, context):
        obj = context.active_object
        obj_mesh = obj.data
        cached_mats = ""
        bm = bmesh.from_edit_mesh(obj_mesh)
        bm.faces.ensure_lookup_table()
        for face in bm.faces:
            if face.select:
                obj_mat_idx = face.material_index
                mat = obj.material_slots[obj_mat_idx].material
                mat_ntn = mat.node_tree.nodes
                mat_txt_img_node_idx = mat_ntn.find("Base Texture")
                if mat_txt_img_node_idx != -1:
                    mat_txt_img_name = mat_ntn[mat_txt_img_node_idx].image.name[:-4]
                    if mat_txt_img_name not in cached_mats:
                        if len(cached_mats) == 0:
                            cached_mats += mat_txt_img_name
                        else:
                            cached_mats += (',' + mat_txt_img_name)
        info_data_idx = bpy.data.texts.find("selected_textures")
        if info_data_idx == -1:
            bpy.data.texts.new("selected_textures")
            info_data_idx = bpy.data.texts.find("selected_textures")
        bpy.data.texts[info_data_idx].clear()
        bpy.data.texts[info_data_idx].write(cached_mats)
        bpy.context.window_manager.clipboard = cached_mats
        self.report({'INFO'}, "Copied! If needed, a copy is under 'selected_textures' inside your text editor.")

    @classmethod
    def poll(cls, context):
        active_object = context.active_object
        return active_object is not None and active_object.type == "MESH" and context.mode == "EDIT_MESH"

    def execute(self, context):
        self.scan_polygons(context)
        return {'FINISHED'}

class GLR_OT_FilterHelper_FileBrowser(Operator):
    """Add selected textures to filter list"""
    bl_idname = "import_glr.add_filter_textures"
    bl_label = "Add Textures"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        if sfile.type != "FILE_BROWSER":
            return False
        operator = sfile.active_operator
        return operator.bl_idname == "IMPORT_SCENE_OT_glr"

    def execute(self, context):
        #print(context.space_data.params.directory)
        if len(context.space_data.active_operator.files) != 0:
            currList = context.space_data.active_operator.filter_options.split(',')
            for file in context.space_data.active_operator.files:
                if file.name[-4:] != ".png" or file.name[:-4] in currList:
                    continue
                if len(context.space_data.active_operator.filter_options) != 0:
                    context.space_data.active_operator.filter_options += (',' + file.name[:-4])
                else:
                    context.space_data.active_operator.filter_options += (file.name[:-4])
        return {'FINISHED'}

class GLR_OT_ImportGLR(Operator, ImportHelper):
    """Import a GLR file"""
    bl_idname = "import_scene.glr"
    bl_label = "Import GLR"
    bl_options = {"PRESET", "UNDO"}

    filename_ext = ".glr"

    filter_glob: StringProperty(
        default="*.glr;*.png",
        options={"HIDDEN"},
        maxlen=255
    )

    files: CollectionProperty(
        type=OperatorFileListElement,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    move: FloatVectorProperty(
        name="Move",
        subtype="TRANSLATION",
        default=(0.0, 0.0, 0.0),
    )

    rotation: FloatVectorProperty(
        name="Rotation",
        subtype="EULER",
        default=(radians(90.0), 0.0, 0.0),
    )

    scale: FloatVectorProperty(
        name="Scale",
        subtype="XYZ",
        default=(1.0, 1.0, 1.0),
    )

    fog_enable: BoolProperty(
        name="Fog BBox",
        description="Import fog wrapping scene bounds",
        default=True
    )

    merge_doubles: BoolProperty(
        name="Merge Triangles",
        description="Remove vertice doubles after import",
        default=True
    )

    enable_srgb: BoolProperty(
        name="Modify Color Management",
        description="Modifies scene color management options to use sRGB",
        default=True
    )

    enable_mat_transparency: BoolProperty(
        name="Enable Material Transparency",
        description="Sets material blend mode to use alpha",
        default=False
    )

    enable_bf_culling: BoolProperty(
        name="Display Backface Culling",
        description="Culls backs of faces based on the normal vector assigned to each triangle",
        default=False,
    )

    VC_enable: BoolVectorProperty(
        name="Vertex",
        size=2,
        default=(True, False)
    )

    PC_enable: BoolVectorProperty(
        name="Primitive",
        size=2,
        default=(False, False)
    )

    EC_enable: BoolVectorProperty(
        name="Environment",
        size=2,
        default=(False, False)
    )

    BC_enable: BoolVectorProperty(
        name="Blend",
        size=2,
        default=(False, False)
    )

    merge_alpha: BoolProperty(
        name="Merge Color Alpha",
        description="Multiply alpha (A) value into each color value (RGB)",
        default=True,
    )

    merge_channels: BoolProperty(
        name="Generate Merged Color Channel",
        description="Combine selected vertex/triangle colors into a single color attribute",
        default=False,
    )

    filter_mode: BoolProperty(
        name="Blacklist",
        description="Blacklist or whitelist mode for chosen filtered textures",
        default=True
    )

    filter_options: StringProperty(
        name="Textures",
        description="Textures to filter"
    )

    remove_no_textures: BoolProperty(
        name="Remove NO_TEXTURE Triangles",
        description="Removes triangles with no textures assigned to them",
        default=False
    )

    WN_WN_override: EnumProperty(
        name="WN_WN (0)",
        items=WM_ENUMS,
        default="WN_WN"
    )

    WN_MN_override: EnumProperty(
        name="WN_MN (1)",
        items=WM_ENUMS,
        default="WN_MN"
    )

    WN_WC_override: EnumProperty(
        name="WN_WC (2)",
        items=WM_ENUMS,
        default="WN_WC"
    )

    WN_MC_override: EnumProperty(
        name="WN_MC (3)",
        items=WM_ENUMS,
        default="WN_MC"
    )

    MN_WN_override: EnumProperty(
        name="MN_WN (4)",
        items=WM_ENUMS,
        default="MN_WN"
    )

    MN_MN_override: EnumProperty(
        name="MN_MN (5)",
        items=WM_ENUMS,
        default="MN_MN"
    )

    MN_WC_override: EnumProperty(
        name="MN_WC (6)",
        items=WM_ENUMS,
        default="MN_WC"
    )

    MN_MC_override: EnumProperty(
        name="MN_MC (7)",
        items=WM_ENUMS,
        default="MN_MC"
    )

    WC_WN_override: EnumProperty(
        name="WC_WN (8)",
        items=WM_ENUMS,
        default="WC_WN"
    )

    WC_MN_override: EnumProperty(
        name="WC_MN (9)",
        items=WM_ENUMS,
        default="WC_MN"
    )

    WC_WC_override: EnumProperty(
        name="WC_WC (10)",
        items=WM_ENUMS,
        default="WC_WC"
    )

    WC_MC_override: EnumProperty(
        name="WC_MC (11)",
        items=WM_ENUMS,
        default="WC_MC"
    )

    MC_WN_override: EnumProperty(
        name="MC_WN (12)",
        items=WM_ENUMS,
        default="MC_WN"
    )

    MC_MN_override: EnumProperty(
        name="MC_MN (13)",
        items=WM_ENUMS,
        default="MC_MN"
    )

    MC_WC_override: EnumProperty(
        name="MC_WC (14)",
        items=WM_ENUMS,
        default="MC_WC"
    )

    MC_MC_override: EnumProperty(
        name="MC_MC (15)",
        items=WM_ENUMS,
        default="MC_MC"
    )

    def execute(self, context):
        from . import import_glr
        keywords = self.as_keywords(ignore=("filter_glob",))
        return import_glr.load(context, **keywords)

    def draw(self, context):
        pass

    def invoke(self, context, event):
        wm = context.window_manager
        wm.fileselect_add(self)
        return {'RUNNING_MODAL'}

class GLR_PT_transform(Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Transform"
    bl_parent_id = "FILE_PT_operator"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator
        return operator.bl_idname == "IMPORT_SCENE_OT_glr"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        sfile = context.space_data
        operator = sfile.active_operator
        layout.prop(operator, "move")
        layout.prop(operator, "rotation")
        layout.prop(operator, "scale")

class GLR_PT_scene(Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Scene"
    bl_parent_id = "FILE_PT_operator"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator
        return operator.bl_idname == "IMPORT_SCENE_OT_glr"

    def draw(self, context):
        layout = self.layout
        sfile = context.space_data
        operator = sfile.active_operator
        row = layout.row()
        row.prop(operator, "fog_enable")
        row.prop(operator, "merge_doubles")
        layout.prop(operator, "enable_srgb")
        layout.prop(operator, "enable_mat_transparency")
        layout.prop(operator, "enable_bf_culling")

class GLR_PT_colors(Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Colors"
    bl_parent_id = "FILE_PT_operator"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator
        return operator.bl_idname == "IMPORT_SCENE_OT_glr"

    def draw(self, context):
        layout = self.layout
        sfile = context.space_data
        operator = sfile.active_operator
        row = layout.row(align=True)
        row.label(text="")
        row.label(text="Enable")
        row.label(text="Invert")
        layout.prop(operator, "VC_enable")
        layout.prop(operator, "PC_enable")
        layout.prop(operator, "EC_enable")
        layout.prop(operator, "BC_enable")
        layout.prop(operator, "merge_alpha")
        layout.prop(operator, "merge_channels")

class GLR_PT_filter(Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Filter"
    bl_parent_id = "FILE_PT_operator"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator
        return operator.bl_idname == "IMPORT_SCENE_OT_glr"

    def draw(self, context):
        layout = self.layout
        sfile = context.space_data
        operator = sfile.active_operator
        row = layout.row()
        row.prop(operator, "filter_mode")
        row.operator(GLR_OT_FilterHelper_FileBrowser.bl_idname)
        layout.prop(operator, "filter_options", icon='TEXTURE')
        layout.prop(operator, "remove_no_textures")

class GLR_PT_wmoverride(Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Wrap Mode Override"
    bl_parent_id = "FILE_PT_operator"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator
        return operator.bl_idname == "IMPORT_SCENE_OT_glr"

    def draw(self, context):
        layout = self.layout
        sfile = context.space_data
        operator = sfile.active_operator
        layout.prop(operator, "WN_WN_override")
        layout.prop(operator, "WN_MN_override")
        layout.prop(operator, "WN_WC_override")
        layout.prop(operator, "WN_MC_override")
        layout.prop(operator, "MN_WN_override")
        layout.prop(operator, "MN_MN_override")
        layout.prop(operator, "MN_WC_override")
        layout.prop(operator, "MN_MC_override")
        layout.prop(operator, "WC_WN_override")
        layout.prop(operator, "WC_MN_override")
        layout.prop(operator, "WC_WC_override")
        layout.prop(operator, "WC_MC_override")
        layout.prop(operator, "MC_WN_override")
        layout.prop(operator, "MC_MN_override")
        layout.prop(operator, "MC_WC_override")
        layout.prop(operator, "MC_MC_override")

def menu_func_import(self, context):
    self.layout.operator(GLR_OT_ImportGLR.bl_idname, text="GLideN64 Rip (.glr)")

CLASSES = (
    GLR_OT_FilterHelper_FileBrowser,
    GLR_OT_FilterHelper_TextureList,
    GLR_OT_ImportGLR,
    GLR_PT_transform,
    GLR_PT_scene,
    GLR_PT_colors,
    GLR_PT_filter,
    GLR_PT_wmoverride
)

def register():
    for cl in CLASSES:
        bpy.utils.register_class(cl)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

def unregister():
    for cl in CLASSES:
        bpy.utils.unregister_class(cl)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)

if __name__ == "__main__":
    register()