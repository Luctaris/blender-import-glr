bl_info = {
    'name': 'GLideN64 Rip (GLR) Importer',
    'author': 'Luctaris, scurest',
    'version': (1, 0, 1),
    'blender': (2, 80, 0),
    'location': 'File > Import',
    'description': 'Import GLR',
    'warning': '',
    'doc_url': 'https://github.com/Luctaris/blender-import-glr/',
    'tracker_url': 'https://github.com/Luctaris/blender-import-glr/issues',
    'category': 'Import-Export',
}

if 'bpy' in locals():
    import importlib
    if 'import_glr' in locals():
        importlib.reload(import_glr)

import os
from math import radians
import bpy
import bmesh
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty, BoolProperty, EnumProperty, FloatProperty, BoolVectorProperty, FloatVectorProperty, CollectionProperty
from bpy.types import Panel, Operator, OperatorFileListElement

class GLR_OT_FilterHelper_TextureList(Operator):
    '''Generates a list of selected materials in edit mode'''
    bl_idname = 'import_glr.gen_filter_list'
    bl_label = 'Generate Texture Filter List'

    def search_polygons_for_textures(self, context):
        obj = context.active_object
        obj_mesh = obj.data
        cached_mats = ''
        bm = bmesh.from_edit_mesh(obj_mesh)
        bm.faces.ensure_lookup_table()
        for face in bm.faces:
            if face.select:
                obj_mat_idx = face.material_index
                mat = obj.material_slots[obj_mat_idx].material
                mat_ntn = mat.node_tree.nodes
                mat_txt_img_node_idx = mat_ntn.find('Texture 0')
                mat_txt_img_name = 'NO_TEXTURE'
                if mat_txt_img_node_idx != -1:
                    mat_txt_img_name = mat_ntn[mat_txt_img_node_idx].image.name[:-4]
                if mat_txt_img_name not in cached_mats:
                    if len(cached_mats) == 0:
                        cached_mats += mat_txt_img_name
                    else:
                        cached_mats += (',' + mat_txt_img_name)
        if cached_mats == '':
            self.report({'ERROR'}, 'No faces selected')
            return
        info_data_idx = bpy.data.texts.find('selected_textures')
        if info_data_idx == -1:
            bpy.data.texts.new('selected_textures')
            info_data_idx = bpy.data.texts.find('selected_textures')
        bpy.data.texts[info_data_idx].clear()
        bpy.data.texts[info_data_idx].write(cached_mats)
        bpy.context.window_manager.clipboard = cached_mats
        self.report({'INFO'}, 'Texture filter list copied!')

    @classmethod
    def poll(cls, context):
        active_object = context.active_object
        return active_object is not None and active_object.type == 'MESH' and context.mode == 'EDIT_MESH'

    def execute(self, context):
        self.search_polygons_for_textures(context)
        return {'FINISHED'}

class GLR_OT_ImportGLR(Operator, ImportHelper):
    '''Import a GLR file'''
    bl_idname = 'import_scene.glr'
    bl_label = 'Import GLR'
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = '.glr'

    filter_glob: StringProperty(
        default='*.glr',
        options={'HIDDEN'},
        maxlen=255
    )

    files: CollectionProperty(
        type=OperatorFileListElement,
        options={'HIDDEN', 'SKIP_SAVE'}
    )

    move: FloatVectorProperty(
        name='Move',
        subtype='TRANSLATION',
        default=(0.0, 0.0, 0.0)
    )

    rotation: FloatVectorProperty(
        name='Rotation',
        subtype='EULER',
        default=(radians(0.0), 0.0, 0.0)
    )

    scale: FloatVectorProperty(
        name='Scale',
        subtype='XYZ',
        default=(1.0, 1.0, 1.0)
    )

    merge_doubles: BoolProperty(
        name='Merge Triangles',
        description='Remove vertice doubles after import',
        default=True
    )

    merge_distance: FloatProperty(
        name='dist',
        description='Distance to merge doubles by',
        min=0.0,
        soft_min=0.0,
        precision=6,
        step=1,
        default=0.001
    )

    enable_srgb: BoolProperty(
        name='Modify Color Management',
        description='Modifies scene color management options to use sRGB',
        default=True
    )

    enable_mat_transparency: BoolProperty(
        name='Enable Material Transparency',
        description='Sets material blend mode to use alpha',
        default=True
    )

    enable_bf_culling: BoolProperty(
        name='Display Backface Culling',
        description='Culls backs of faces based on the normal vector assigned to each triangle',
        default=False
    )

    gen_light_color_attribute: BoolProperty(
        name='Generate \'Lighting\' Color Attribute',
        description='Generate a color attribute which contains all combined lighting colors influencing triangles',
        default=False
    )

    gen_overlay_color_attribute: BoolProperty(
        name='Generate \'Overlay\' Color Attribute',
        description='Generate a color attribute which contains all combined overlay colors influencing triangles',
        default=False
    )

    filter_mode: BoolProperty(
        name='Blacklist',
        description='Blacklist or whitelist mode for chosen filtered textures',
        default=True
    )

    filter_list: StringProperty(
        name='Textures',
        description='Textures to filter'
    )

    def execute(self, context):
        from . import import_glr
        keywords = self.as_keywords(ignore=('filter_glob',))
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
    bl_label = 'Transform'
    bl_parent_id = 'FILE_PT_operator'

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator
        return operator.bl_idname == 'IMPORT_SCENE_OT_glr'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        sfile = context.space_data
        operator = sfile.active_operator
        layout.prop(operator, 'move')
        layout.prop(operator, 'rotation')
        layout.prop(operator, 'scale')

class GLR_PT_scene(Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = 'Scene'
    bl_parent_id = 'FILE_PT_operator'

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator
        return operator.bl_idname == 'IMPORT_SCENE_OT_glr'

    def draw(self, context):
        layout = self.layout
        sfile = context.space_data
        operator = sfile.active_operator
        row = layout.row()
        row.prop(operator, 'merge_doubles')
        row.prop(operator, 'merge_distance')
        layout.prop(operator, 'enable_srgb')
        layout.prop(operator, 'enable_mat_transparency')
        layout.prop(operator, 'enable_bf_culling')

class GLR_PT_colors(Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = 'Colors'
    bl_parent_id = 'FILE_PT_operator'

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator
        return operator.bl_idname == 'IMPORT_SCENE_OT_glr'

    def draw(self, context):
        layout = self.layout
        sfile = context.space_data
        operator = sfile.active_operator
        layout.prop(operator, 'gen_light_color_attribute')
        layout.prop(operator, 'gen_overlay_color_attribute')

class GLR_PT_filter(Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = 'Filter'
    bl_parent_id = 'FILE_PT_operator'

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator
        return operator.bl_idname == 'IMPORT_SCENE_OT_glr'

    def draw(self, context):
        layout = self.layout
        sfile = context.space_data
        operator = sfile.active_operator
        row = layout.row()
        row.prop(operator, 'filter_mode')
        layout.prop(operator, 'filter_list', icon='TEXTURE')

def menu_func_import(self, context):
    self.layout.operator(GLR_OT_ImportGLR.bl_idname, text='GLideN64 Rip (.glr)')

CLASSES = (
    GLR_OT_FilterHelper_TextureList,
    GLR_OT_ImportGLR,
    GLR_PT_transform,
    GLR_PT_scene,
   #GLR_PT_colors, #TODO: Implement correctly
    GLR_PT_filter
)

def register():
    for cl in CLASSES:
        bpy.utils.register_class(cl)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

def unregister():
    for cl in CLASSES:
        bpy.utils.unregister_class(cl)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)

if __name__ == '__main__':
    register()