from django.shortcuts import render, redirect, get_object_or_404
from .models import Session, Photo, Frame, RenderedPhoto, PhotoSlot
from django.core.files.base import ContentFile
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
from PIL import Image
from io import BytesIO
from pillow_heif import register_heif_opener
from firebase_admin import storage
import qrcode
import zipfile
import os
import json

# Đăng ký hỗ trợ HEIC/HEIF
register_heif_opener()

# ====== FIREBASE UPLOAD FUNCTION ======
def upload_to_firebase(file_bytes, file_name, session_phone):
    """
    Upload file to Firebase Storage organized by session folder
    Path: renders/session_{phone}/{file_name}
    """
    try:
        bucket = storage.bucket()
        
        # Organize by session folder
        folder_path = f"renders/session_{session_phone}/{file_name}"
        print(f"📁 Uploading to: {folder_path}")
        
        blob = bucket.blob(folder_path)
        blob.upload_from_string(file_bytes, content_type='image/jpeg')
        blob.make_public()
        
        print(f"✅ Upload successful: {blob.public_url}")
        return blob.public_url
    except Exception as e:
        print(f"❌ Firebase upload error: {e}")
        import traceback
        traceback.print_exc()
        return None

# ====== QR CODE GENERATION FUNCTION ======
def generate_qr_code(url):
    """Tạo mã QR từ URL và trả về BytesIO object"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    return buffer

# ====== FIREBASE LIST FILES FUNCTION ======
def list_firebase_files(session_phone):
    """
    Lấy danh sách tất cả file ảnh từ Firebase Storage theo session
    Returns: list of dicts with 'name', 'url', 'created_at'
    """
    try:
        bucket = storage.bucket()
        prefix = f"renders/session_{session_phone}/"
        
        print(f"🔍 Listing files from Firebase: {prefix}")
        blobs = bucket.list_blobs(prefix=prefix)
        
        files = []
        for blob in blobs:
            # Chỉ lấy file ảnh, bỏ qua folder
            if blob.name.endswith(('.jpg', '.jpeg', '.png')):
                blob.make_public()  # Đảm bảo public
                files.append({
                    'name': blob.name.split('/')[-1],  # Lấy tên file
                    'url': blob.public_url,
                    'created_at': blob.time_created,
                })
        
        print(f"✅ Found {len(files)} files in Firebase")
        return sorted(files, key=lambda x: x['created_at'], reverse=True)
    except Exception as e:
        print(f"❌ Firebase list error: {e}")
        import traceback
        traceback.print_exc()
        return []

# Create your views here.
def home(request):
    # Form nhập số điện thoại - redirect to new workflow
    if request.method == "POST":
        phone = request.POST.get("phone", "").strip()
        if phone:
            return redirect(f"/session/{phone}/frame-selection/")
    return render(request, "core/home.html")

def session_home(request, phone):
    # Màn hình chọn: chụp mới / xem ảnh cũ
    return render(request, "core/session_home.html", {"phone": phone})

def session_photos(request, phone):
    session, created = Session.objects.get_or_create(phone=phone)

    if request.method == "POST" and request.FILES.getlist("photos"):
        for img in request.FILES.getlist("photos"):
            Photo.objects.create(session=session, image=img)
        return redirect(f"/session/{phone}/photos/")

    frames = Frame.objects.filter(active=True)
    photos = session.photos.all()
    
    # Thêm thông tin số slot cho mỗi frame
    for frame in frames:
        frame.max_slots = len(frame.layout_json.get("slots", []))

    return render(request, "core/session_photos.html", {
        "session": session,
        "photos": photos,
        "frames": frames,
    })


# ======= XỬ LÝ GHÉP FRAME =======
def render_frame_view(request, phone):
    session = Session.objects.get(phone=phone)

    if request.method == "POST":
        frame_id = request.POST.get("frame_id")
        frame = Frame.objects.get(id=frame_id)
        
        # Kiểm tra số lượng ảnh
        max_slots = len(frame.layout_json.get("slots", []))
        photos = list(session.photos.all())
        
        if len(photos) < max_slots:
            # Chưa đủ ảnh, quay lại với thông báo
            frames = Frame.objects.filter(active=True)
            for f in frames:
                f.max_slots = len(f.layout_json.get("slots", []))
            
            return render(request, "core/session_photos.html", {
                "session": session,
                "photos": photos,
                "frames": frames,
                "error_message": f"Frame này cần {max_slots} ảnh, bạn mới có {len(photos)} ảnh. Vui lòng upload thêm!",
            })

        # Lấy ảnh session (chỉ lấy đúng số lượng slot)
        photos = photos[:max_slots]

        print(f"🎨 Starting render for phone: {phone}, frame: {frame.id}")
        final_image = render_frame(photos, frame)
        
        # Đọc buffer một lần và lưu vào biến
        image_bytes = final_image.getvalue()
        print(f"📦 Image bytes size: {len(image_bytes)}")

        # Lưu thành RenderedPhoto
        rendered = RenderedPhoto(session=session, frame=frame)
        file_name = f"render_{phone}_{frame.id}.jpg"
        rendered.image.save(file_name, ContentFile(image_bytes))
        rendered.save()
        print(f"💾 RenderedPhoto saved with ID: {rendered.id}")

        try:
            # ==== UPLOAD TO FIREBASE ====
            firebase_file = f"{phone}_{rendered.id}.jpg"
            print(f"🔄 Uploading to Firebase: renders/session_{phone}/{firebase_file}")
            firebase_url = upload_to_firebase(image_bytes, firebase_file, phone)
            print(f"📡 Firebase URL: {firebase_url}")

            # Nếu Firebase fail, dùng local URL
            if not firebase_url:
                print("⚠️  Firebase upload failed, using local URL instead")
                # Tạo local URL (sẽ hoạt động trong local network)
                firebase_url = f"http://127.0.0.1:8000{rendered.image.url}"
                print(f"🔗 Using local URL: {firebase_url}")

            # Lưu URL vào session
            session.download_url = firebase_url
            session.save()
            print(f"✅ Session download_url saved: {firebase_url}")

            # ==== TẠO MÃ QR ====
            print(f"🔄 Generating QR code for: {firebase_url}")
            qr_buffer = generate_qr_code(firebase_url)
            qr_file_name = f"qr_{phone}_{rendered.id}.png"
            
            # Lưu QR code vào RenderedPhoto
            print(f"💾 Saving QR code: {qr_file_name}")
            rendered.qr_code.save(qr_file_name, ContentFile(qr_buffer.read()))
            rendered.save()  # Save lại để lưu QR code
            print(f"✅ QR code saved successfully!")
            print(f"📂 QR path: {rendered.qr_code.name if rendered.qr_code else 'None'}")
        except Exception as e:
            print(f"❌ Error in Firebase/QR process: {e}")
            import traceback
            traceback.print_exc()

        return redirect(f"/session/{phone}/preview/")

    return redirect(f"/session/{phone}/photos/")


# ====== FUNCTION GHÉP FRAME ======
def render_frame(list_photos, frame_obj):
    layout = frame_obj.layout_json
    frame_path = frame_obj.image.path

    # Canvas theo kích thước frame
    canvas_w = layout.get("w", 1200)
    canvas_h = layout.get("h", 1800)
    
    # Bước 1: Tạo canvas nền trắng
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (255, 255, 255, 255))
    
    # Bước 2: Mở frame PNG và paste TRƯỚC
    frame_png = Image.open(frame_path).convert("RGBA")
    if frame_png.size != (canvas_w, canvas_h):
        frame_png = frame_png.resize((canvas_w, canvas_h), Image.Resampling.LANCZOS)
    
    # Paste frame lên canvas (frame là layer dưới)
    canvas.paste(frame_png, (0, 0), frame_png)
    
    # Bước 3: Paste các ảnh vào slots với crop center đúng chuẩn
    for idx, slot in enumerate(layout["slots"]):
        if idx >= len(list_photos):
            break

        img_path = list_photos[idx].image.path
        img = Image.open(img_path).convert("RGB")
        
        # Lấy kích thước slot
        slot_w = slot["w"]
        slot_h = slot["h"]
        slot_ratio = slot_w / slot_h
        
        # Lấy kích thước ảnh gốc
        img_w, img_h = img.size
        img_ratio = img_w / img_h
        
        # B1: Crop center theo tỷ lệ slot
        if img_ratio > slot_ratio:
            # Ảnh rộng hơn → crop chiều rộng
            new_w = int(img_h * slot_ratio)
            new_h = img_h
            left = (img_w - new_w) // 2
            top = 0
            right = left + new_w
            bottom = img_h
        else:
            # Ảnh cao hơn → crop chiều cao
            new_w = img_w
            new_h = int(img_w / slot_ratio)
            left = 0
            top = (img_h - new_h) // 2
            right = img_w
            bottom = top + new_h
        
        cropped = img.crop((left, top, right, bottom))
        
        # B2: Resize đúng kích thước slot
        resized = cropped.resize((slot_w, slot_h), Image.Resampling.LANCZOS)
        
        # B3: Paste vào đúng vị trí
        canvas.paste(resized, (slot["x"], slot["y"]))

    # Bước 4: Xuất file JPG
    buffer = BytesIO()
    canvas.convert("RGB").save(buffer, format="JPEG", quality=95, dpi=(300, 300))
    buffer.seek(0)
    return buffer


def session_preview(request, phone):
    # Màn hình xem ảnh đã render
    session = Session.objects.get(phone=phone)
    renders = session.renders.all().order_by('-created_at')
    return render(request, "core/session_preview.html", {
        "phone": phone,
        "session": session,
        "renders": renders,
    })

def print_photo(request, phone):
    # Mock: mô phỏng in ảnh
    session = Session.objects.get(phone=phone)
    latest_render = session.renders.order_by('-created_at').first()
    
    return render(request, "core/print_confirm.html", {
        "phone": phone,
        "render": latest_render,
    })

def delete_photo(request, phone, photo_id):
    # Xóa ảnh đã upload
    photo = Photo.objects.get(id=photo_id, session__phone=phone)
    photo.image.delete()  # Xóa file trên disk
    photo.delete()  # Xóa record trong DB
    return redirect(f"/session/{phone}/photos/")

def download_session(request, phone):
    """Trang tải tất cả ảnh của session - lấy từ Firebase Storage"""
    try:
        # Lấy session (hoặc tạo mới nếu chưa có)
        session, created = Session.objects.get_or_create(phone=phone)
        
        # Lấy danh sách file từ Firebase
        firebase_files = list_firebase_files(phone)
        
        # Nếu request download ZIP
        if request.GET.get('download') == 'zip':
            # Kiểm tra có ảnh không
            if not firebase_files:
                return redirect(f"/d/{phone}/")
            
            # Tạo ZIP file trong memory từ Firebase URLs
            import requests
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for idx, file_info in enumerate(firebase_files, 1):
                    try:
                        # Download ảnh từ Firebase
                        response = requests.get(file_info['url'], timeout=10)
                        if response.status_code == 200:
                            # Thêm vào ZIP với tên đẹp
                            zip_file.writestr(f"photo_{idx}.jpg", response.content)
                            print(f"✅ Added to ZIP: {file_info['name']}")
                    except Exception as e:
                        print(f"❌ Error downloading {file_info['name']}: {e}")
            
            # Trả về ZIP file
            zip_buffer.seek(0)
            response = HttpResponse(zip_buffer.read(), content_type='application/zip')
            response['Content-Disposition'] = f'attachment; filename="session_{phone}_photos.zip"'
            return response
        
        # Generate QR code cho download page
        download_url = f"{request.scheme}://{request.get_host()}/d/{phone}/"
        qr_code_url = None
        if firebase_files:
            try:
                qr_buffer = generate_qr_code(download_url)
                # Convert to base64 để hiển thị trực tiếp
                import base64
                qr_code_url = "data:image/png;base64," + base64.b64encode(qr_buffer.read()).decode()
            except Exception as e:
                print(f"❌ QR generation error: {e}")
        
        # Hiển thị trang download với Firebase files
        return render(request, "core/download_session.html", {
            "phone": phone,
            "session": session,
            "firebase_files": firebase_files,
            "qr_code_url": qr_code_url,
            "download_url": download_url,
        })
    except Exception as e:
        print(f"❌ Download session error: {e}")
        import traceback
        traceback.print_exc()
        return redirect('home')


# ========================================
# WORKFLOW PHOTOBOOTH CHUYÊN NGHIỆP
# ========================================

def frame_selection(request, phone):
    """Bước 1: Chọn frame và hiển thị các slot cần điền ảnh"""
    session, created = Session.objects.get_or_create(phone=phone)
    
    if request.method == "POST":
        frame_id = request.POST.get("frame_id")
        frame = get_object_or_404(Frame, id=frame_id)
        
        # Lưu frame được chọn vào session
        session.selected_frame = frame
        session.save()
        
        # Clear old slots if any
        PhotoSlot.objects.filter(session=session).delete()
        
        return redirect(f"/session/{phone}/slot-manager/")
    
    frames = Frame.objects.filter(active=True)
    for frame in frames:
        frame.slot_count = len(frame.layout_json.get("slots", []))
    
    return render(request, "core/frame_selection.html", {
        "session": session,
        "phone": phone,
        "frames": frames,
    })


def slot_manager(request, phone):
    """Bước 2: Quản lý các slot - upload/gán/xóa/thay ảnh"""
    session = get_object_or_404(Session, phone=phone)
    
    if not session.selected_frame:
        return redirect(f"/session/{phone}/frame-selection/")
    
    frame = session.selected_frame
    slots_data = frame.layout_json.get("slots", [])
    
    # Lấy tất cả ảnh đã upload của session
    uploaded_photos = session.photos.all().order_by('-created_at')
    
    # Lấy slots đã được gán ảnh
    assigned_slots = {
        slot.slot_index: slot
        for slot in PhotoSlot.objects.filter(session=session, frame=frame).select_related('photo')
    }
    
    # Tạo danh sách slots với thông tin gán ảnh
    slots_info = []
    for idx, slot_data in enumerate(slots_data):
        assigned_slot = assigned_slots.get(idx)
        slots_info.append({
            'index': idx,
            'position': slot_data,
            'assigned_photo': assigned_slot.photo if assigned_slot else None,
            'is_filled': assigned_slot is not None,
        })
    
    # Kiểm tra đủ ảnh chưa
    filled_count = sum(1 for s in slots_info if s['is_filled'])
    all_filled = filled_count == len(slots_data)
    
    return render(request, "core/slot_manager.html", {
        "session": session,
        "phone": phone,
        "frame": frame,
        "slots_info": slots_info,
        "uploaded_photos": uploaded_photos,
        "all_filled": all_filled,
        "filled_count": filled_count,
        "total_slots": len(slots_data),
    })


@require_POST
def upload_photo(request, phone):
    """Upload ảnh mới vào session (chưa gán vào slot)"""
    session = get_object_or_404(Session, phone=phone)
    
    uploaded_files = request.FILES.getlist("photos")
    created_photos = []
    
    for img_file in uploaded_files:
        photo = Photo.objects.create(session=session, image=img_file)
        created_photos.append({
            'id': photo.id,
            'url': photo.image.url,
            'created_at': photo.created_at.isoformat(),
        })
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'photos': created_photos})
    
    return redirect(f"/session/{phone}/slot-manager/")


@require_POST
def assign_photo_to_slot(request, phone):
    """Gán ảnh vào slot cụ thể"""
    session = get_object_or_404(Session, phone=phone)
    
    if not session.selected_frame:
        return JsonResponse({'success': False, 'error': 'No frame selected'}, status=400)
    
    try:
        data = json.loads(request.body)
        photo_id = data.get('photo_id')
        slot_index = data.get('slot_index')
        
        photo = get_object_or_404(Photo, id=photo_id, session=session)
        frame = session.selected_frame
        
        # Check slot index valid
        slots = frame.layout_json.get("slots", [])
        if slot_index >= len(slots):
            return JsonResponse({'success': False, 'error': 'Invalid slot index'}, status=400)
        
        # Tạo hoặc update slot assignment
        photo_slot, created = PhotoSlot.objects.update_or_create(
            session=session,
            frame=frame,
            slot_index=slot_index,
            defaults={'photo': photo}
        )
        
        return JsonResponse({
            'success': True,
            'slot_index': slot_index,
            'photo_url': photo.image.url,
            'photo_id': photo.id,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@require_POST
def remove_photo_from_slot(request, phone):
    """Xóa ảnh khỏi slot (không xóa ảnh gốc)"""
    session = get_object_or_404(Session, phone=phone)
    
    try:
        data = json.loads(request.body)
        slot_index = data.get('slot_index')
        
        PhotoSlot.objects.filter(
            session=session,
            frame=session.selected_frame,
            slot_index=slot_index
        ).delete()
        
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


def preview_frame_live(request, phone):
    """Bước 3: Xem thử frame với ảnh thật (live preview)"""
    session = get_object_or_404(Session, phone=phone)
    
    if not session.selected_frame:
        return redirect(f"/session/{phone}/frame-selection/")
    
    frame = session.selected_frame
    
    # Lấy các slots đã gán ảnh theo thứ tự
    assigned_slots = PhotoSlot.objects.filter(
        session=session,
        frame=frame
    ).select_related('photo').order_by('slot_index')
    
    # Check đủ ảnh chưa
    required_slots = len(frame.layout_json.get("slots", []))
    has_all_photos = assigned_slots.count() == required_slots
    
    return render(request, "core/preview_frame.html", {
        "session": session,
        "phone": phone,
        "frame": frame,
        "assigned_slots": assigned_slots,
        "has_all_photos": has_all_photos,
        "required_slots": required_slots,
    })


@require_POST
def finalize_render(request, phone):
    """Bước 4: Ghép ảnh chính thức, tạo QR, upload Firebase"""
    session = get_object_or_404(Session, phone=phone)
    
    if not session.selected_frame:
        return JsonResponse({'success': False, 'error': 'No frame selected'}, status=400)
    
    frame = session.selected_frame
    slots_data = frame.layout_json.get("slots", [])
    
    # Lấy ảnh đã gán theo thứ tự slot
    assigned_slots = PhotoSlot.objects.filter(
        session=session,
        frame=frame
    ).select_related('photo').order_by('slot_index')
    
    if assigned_slots.count() < len(slots_data):
        return JsonResponse({
            'success': False,
            'error': f'Chưa đủ ảnh. Cần {len(slots_data)} ảnh, hiện có {assigned_slots.count()}'
        }, status=400)
    
    # Lấy danh sách Photo objects theo thứ tự slot
    photos_ordered = [slot.photo for slot in assigned_slots]
    
    try:
        # Render frame
        print(f"🎨 Starting final render for {phone}")
        final_image = render_frame(photos_ordered, frame)
        image_bytes = final_image.getvalue()
        
        # Lưu RenderedPhoto
        rendered = RenderedPhoto(session=session, frame=frame)
        file_name = f"render_{phone}_{frame.id}_{len(session.renders.all()) + 1}.jpg"
        rendered.image.save(file_name, ContentFile(image_bytes))
        rendered.save()
        
        # Upload to Firebase
        firebase_file = f"{phone}_{rendered.id}.jpg"
        firebase_url = upload_to_firebase(image_bytes, firebase_file, phone)
        
        if not firebase_url:
            firebase_url = f"http://127.0.0.1:8000{rendered.image.url}"
        
        # Lưu URL
        session.download_url = firebase_url
        session.save()
        
        # Tạo QR code
        qr_buffer = generate_qr_code(firebase_url)
        qr_file_name = f"qr_{phone}_{rendered.id}.png"
        rendered.qr_code.save(qr_file_name, ContentFile(qr_buffer.read()))
        rendered.save()
        
        print(f"✅ Final render completed: {rendered.id}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'render_id': rendered.id,
                'image_url': rendered.image.url,
                'qr_url': rendered.qr_code.url if rendered.qr_code else None,
                'firebase_url': firebase_url,
            })
        
        return redirect(f"/session/{phone}/preview/")
        
    except Exception as e:
        print(f"❌ Render error: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)