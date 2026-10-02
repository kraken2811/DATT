# Vehicle Watchlist API Contract & Architecture Specification

## Overview

Current extension (schema 0011): the existing CRUD accepts/returns nullable
`vehicle_color` with values `black|white|gray|silver|red|blue|green|yellow|orange|brown|other`.
The UI no longer edits `name`/`display_name` or `owner_info`; legacy API fields
remain available. Matching is confirmed-plate-only, regardless of declared or
detected color. See [current backend contract](vehicle-watchlist-backend.md)
for event metadata and rollout requirements; the older examples below retain
legacy fields for backward compatibility.

This document specifies the unified **Vehicle Watchlist API Contract** for the DATT Intelligent Surveillance Platform. 
It defines the endpoints, request/response payloads, error handling, and the end-to-end integration lifecycle linking License Plate Detection, OCR, Watchlist Matching, and Historical Detection Tracing.

---

## 1. Data Schema

### 1.1 Vehicle Watchlist Entity
| Field | Type | Required | Description | Example |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `UUID / string` | System | Unique identifier of the vehicle entry | `"4f9b8c21-7e3d-4a12-89bc-6e543210abcd"` |
| `plate_number` | `string` | **Yes** | Human-readable plate representation | `"29A-123.45"` |
| `normalized_plate` | `string` | System | Stripped & uppercase normalized plate | `"29A12345"` |
| `vehicle_type` | `string` | No | Vehicle classification | `"car"`, `"motorbike"`, `"truck"`, `"bus"`, `"container"`, `"other"` |
| `name` | `string` | No | Friendly alias or designation | `"Xe đối tượng nghi vấn"` |
| `owner_info` | `string` | No | Owner identity or organization | `"Nguyễn Văn A - 0987654321"` |
| `notes` | `string` | No | Operational / security notes | `"Theo dõi cổng số 2 giờ cao điểm"` |
| `status` | `string` | No | Monitoring status (`"active"` / `"disabled"`) | `"active"` |
| `image_path` | `string` | No | Reference vehicle image if available | `"/data/uploads/vehicles/plate.jpg"` |
| `detection_count` | `integer` | System | Total matching detections recorded | `12` |
| `last_seen` | `string` | System | ISO 8601 timestamp of latest match | `"2026-10-01T14:32:16Z"` |
| `created_at` | `string` | System | ISO 8601 creation timestamp | `"2026-10-01T08:00:00Z"` |
| `updated_at` | `string` | System | ISO 8601 last modified timestamp | `"2026-10-01T14:00:00Z"` |

---

## 2. API Endpoints

### 2.1 List All Vehicle Watchlist Items
- **Endpoint**: `GET /api/watchlist/vehicles`
- **Query Parameters**:
  - `status` *(optional)*: Filter by `"active"` or `"disabled"`
  - `vehicle_type` *(optional)*: Filter by type
  - `search` *(optional)*: Query matching `plate_number`, `normalized_plate`, `name`, or `owner_info`
- **Response `200 OK`**:
```json
{
  "status": "ok",
  "total": 2,
  "vehicles": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "plate_number": "29A-123.45",
      "normalized_plate": "29A12345",
      "vehicle_type": "car",
      "name": "Xe giám sát đặc biệt",
      "owner_info": "Trần Văn C",
      "notes": "Kiểm tra kỹ tại trạm thu phí",
      "status": "active",
      "image_path": null,
      "detection_count": 8,
      "last_seen": "2026-10-01T14:22:00Z",
      "created_at": "2026-10-01T08:15:00Z",
      "updated_at": "2026-10-01T08:15:00Z"
    }
  ]
}
```

---

### 2.2 Create / Register Vehicle to Watchlist
- **Endpoint**: `POST /api/watchlist/vehicles`
- **Headers**: `Content-Type: application/json` or `multipart/form-data`
- **Request Body**:
```json
{
  "plate_number": "30K-567.89",
  "vehicle_type": "car",
  "name": "Xe khách VIP",
  "owner_info": "Tập đoàn ABC",
  "notes": "Ưu tiên luồng xanh",
  "status": "active"
}
```
- **Validation Rules**:
  - `plate_number`: Required, trimmed, uppercase, normalized (alphanumeric only check).
  - `vehicle_type`: Default `"car"` if omitted.
  - `status`: Default `"active"`.
- **Response `201 Created` / `200 OK`**:
```json
{
  "status": "ok",
  "message": "Vehicle added to watchlist successfully",
  "vehicle": {
    "id": "7a3e8102-1234-4567-89ab-cdef01234567",
    "plate_number": "30K-567.89",
    "normalized_plate": "30K56789",
    "vehicle_type": "car",
    "name": "Xe khách VIP",
    "owner_info": "Tập đoàn ABC",
    "notes": "Ưu tiên luồng xanh",
    "status": "active",
    "detection_count": 0,
    "last_seen": null,
    "created_at": "2026-10-01T15:40:00Z",
    "updated_at": "2026-10-01T15:40:00Z"
  }
}
```

---

### 2.3 Get Vehicle Watchlist Item by ID
- **Endpoint**: `GET /api/watchlist/vehicles/{id}`
- **Response `200 OK`**:
```json
{
  "status": "ok",
  "vehicle": {
    "id": "7a3e8102-1234-4567-89ab-cdef01234567",
    "plate_number": "30K-567.89",
    "normalized_plate": "30K56789",
    "vehicle_type": "car",
    "name": "Xe khách VIP",
    "owner_info": "Tập đoàn ABC",
    "notes": "Ưu tiên luồng xanh",
    "status": "active",
    "detection_count": 2,
    "last_seen": "2026-10-01T15:20:10Z",
    "created_at": "2026-10-01T15:40:00Z",
    "updated_at": "2026-10-01T15:40:00Z"
  }
}
```
- **Response `404 Not Found`**:
```json
{
  "status": "error",
  "code": "VEHICLE_NOT_FOUND",
  "message": "Vehicle with ID '...' not found"
}
```

---

### 2.4 Update / Toggle Vehicle Watchlist Item
- **Endpoint**: `PATCH /api/watchlist/vehicles/{id}`
- **Request Body**:
```json
{
  "status": "disabled",
  "notes": "Đã hoàn thành kiểm tra, tạm dừng theo dõi"
}
```
- **Response `200 OK`**:
```json
{
  "status": "ok",
  "message": "Vehicle updated successfully",
  "vehicle": { ... }
}
```

---

### 2.5 Delete Vehicle from Watchlist
- **Endpoint**: `DELETE /api/watchlist/vehicles/{id}`
- **Response `200 OK`**:
```json
{
  "status": "ok",
  "message": "Vehicle removed from watchlist"
}
```

---

### 2.6 Get Detection History for Vehicle
- **Endpoint**: `GET /api/watchlist/vehicles/{id}/detections`
- **Query Parameters**:
  - `limit` *(integer, default 50)*
  - `offset` *(integer, default 0)*
- **Response `200 OK`**:
```json
{
  "status": "ok",
  "vehicle_id": "7a3e8102-1234-4567-89ab-cdef01234567",
  "plate_number": "30K-567.89",
  "total_detections": 1,
  "detections": [
    {
      "id": "e9124a1b-c741-4cf1-84e5-927361ad291b",
      "plate_text": "30K-567.89",
      "confidence": 0.94,
      "plate_crop_path": "data/events/plate_20261001_142200_cam02.jpg",
      "vehicle_image_path": "data/events/vehicle_20261001_142200_cam02.jpg",
      "camera_id": "Camera 02",
      "created_at": "2026-10-01T14:22:00Z"
    }
  ]
}
```

---

## 3. Future Matching & Notification Pipeline Flow

```
+-------------------------------------------------------+
|                       CAMERA                          |
|             (RTSP / MJPEG / HLS Stream)               |
+-------------------------------------------------------+
                           |
                           v
+-------------------------------------------------------+
|                  VEHICLE DETECTION                    |
|             (YOLO11s Detection / Tracking)            |
+-------------------------------------------------------+
                           |
                           v
+-------------------------------------------------------+
|                   PLATE DETECTION                     |
|           (Bounding Box Localization)                 |
+-------------------------------------------------------+
                           |
                           v
+-------------------------------------------------------+
|                     PLATE OCR                         |
|         (Character Recognition & Confidence)          |
+-------------------------------------------------------+
                           |
                           v
+-------------------------------------------------------+
|                 NORMALIZED PLATE                      |
|       (Trim, Uppercase, Strip Special Chars)          |
+-------------------------------------------------------+
                           |
                           v
+-------------------------------------------------------+
|                VEHICLE WATCHLIST                      |
|          (In-Memory / Fast Indexed Lookup)            |
+-------------------------------------------------------+
                           |
                           v
                     [ MATCH? ]
                     /        \
                   YES         NO
                  /             \
                 v               v
+------------------------+   +------------------------+
|   DETECTION HISTORY    |   |  Standard Plate Event  |
|  (PlateEvent & Passage)|   |    Logging Only        |
+------------------------+   +------------------------+
            |
            v
+------------------------+
|      ALERT ENGINE      |
|  - In-app Live Toast   |
|  - Slack Notification  |
|  - Telegram Dispatch   |
+------------------------+
```

*(Note: Alerts to Slack / Telegram are isolated and out of scope for this UI frontend task).*
