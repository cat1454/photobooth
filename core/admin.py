from django.contrib import admin
from .models import Frame, Session, Photo, RenderedPhoto

# Customize Frame admin
@admin.register(Frame)
class FrameAdmin(admin.ModelAdmin):
    list_display = ('name', 'active', 'get_slots_count', 'image_preview')
    list_filter = ('active',)
    search_fields = ('name',)
    list_editable = ('active',)
    
    def get_slots_count(self, obj):
        return len(obj.layout_json.get('slots', []))
    get_slots_count.short_description = 'Số ô'
    
    def image_preview(self, obj):
        if obj.image:
            return f'<img src="{obj.image.url}" width="100" />'
        return '-'
    image_preview.short_description = 'Preview'
    image_preview.allow_tags = True

# Customize Session admin
@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ('phone', 'created_at', 'photo_count', 'render_count')
    search_fields = ('phone',)
    date_hierarchy = 'created_at'
    
    def photo_count(self, obj):
        return obj.photos.count()
    photo_count.short_description = 'Số ảnh'
    
    def render_count(self, obj):
        return obj.renders.count()
    render_count.short_description = 'Đã render'

# Customize Photo admin
@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'created_at', 'image_preview')
    list_filter = ('created_at',)
    search_fields = ('session__phone',)
    date_hierarchy = 'created_at'
    
    def image_preview(self, obj):
        if obj.image:
            return f'<img src="{obj.image.url}" width="80" />'
        return '-'
    image_preview.short_description = 'Preview'
    image_preview.allow_tags = True

# Customize RenderedPhoto admin
@admin.register(RenderedPhoto)
class RenderedPhotoAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'frame', 'created_at', 'image_preview')
    list_filter = ('created_at', 'frame')
    search_fields = ('session__phone',)
    date_hierarchy = 'created_at'
    
    def image_preview(self, obj):
        if obj.image:
            return f'<img src="{obj.image.url}" width="100" />'
        return '-'
    image_preview.short_description = 'Preview'
    image_preview.allow_tags = True

