from django.urls import path
from . import views

urlpatterns = [
    # Home & Session
    path("", views.home, name="home"),
    path("session/<str:phone>/", views.session_home, name="session_home"),
    
    # OLD WORKFLOW (giữ lại để backward compatible)
    path("session/<str:phone>/photos/", views.session_photos, name="session_photos"),
    path("session/<str:phone>/delete/<int:photo_id>/", views.delete_photo, name="delete_photo"),
    path("session/<str:phone>/render/", views.render_frame_view, name="render_frame"),
    path("session/<str:phone>/preview/", views.session_preview, name="session_preview"),
    path("session/<str:phone>/print/", views.print_photo, name="print_photo"),
    
    # NEW PROFESSIONAL WORKFLOW
    path("session/<str:phone>/frame-selection/", views.frame_selection, name="frame_selection"),
    path("session/<str:phone>/slot-manager/", views.slot_manager, name="slot_manager"),
    path("session/<str:phone>/upload/", views.upload_photo, name="upload_photo"),
    path("session/<str:phone>/assign-slot/", views.assign_photo_to_slot, name="assign_slot"),
    path("session/<str:phone>/remove-slot/", views.remove_photo_from_slot, name="remove_slot"),
    path("session/<str:phone>/preview-frame/", views.preview_frame_live, name="preview_frame_live"),
    path("session/<str:phone>/finalize-render/", views.finalize_render, name="finalize_render"),
    
    # Download Page
    path("d/<str:phone>/", views.download_session, name="download_session"),
]
