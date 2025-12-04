from django.db import models

# Create your models here.
from django.db import models

class Frame(models.Model):
    name = models.CharField(max_length=100)
    image = models.ImageField(upload_to="frames/")
    # JSON describe vị trí các slot ảnh trong frame
    layout_json = models.JSONField()
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

class Session(models.Model):
    phone = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)
    download_url = models.URLField(max_length=500, blank=True, null=True)
    selected_frame = models.ForeignKey(Frame, on_delete=models.SET_NULL, null=True, blank=True, related_name="sessions")

    def __str__(self):
        return f"Session {self.phone} - {self.created_at:%Y-%m-%d %H:%M}"

class Photo(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="photos/")
    created_at = models.DateTimeField(auto_now_add=True)

class PhotoSlot(models.Model):
    """Quản lý ảnh được gán vào từng slot của frame"""
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="slots")
    frame = models.ForeignKey(Frame, on_delete=models.CASCADE)
    slot_index = models.IntegerField()  # Vị trí slot trong layout_json (0, 1, 2...)
    photo = models.ForeignKey(Photo, on_delete=models.CASCADE, related_name="assignments")
    order = models.IntegerField(default=0)  # Thứ tự hiển thị
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['session', 'frame', 'slot_index']
        ordering = ['order', 'slot_index']

    def __str__(self):
        return f"Slot {self.slot_index} - Session {self.session.phone}"

class RenderedPhoto(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="renders")
    frame = models.ForeignKey(Frame, on_delete=models.SET_NULL, null=True)
    image = models.ImageField(upload_to="renders/")
    qr_code = models.ImageField(upload_to="qrcodes/", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
