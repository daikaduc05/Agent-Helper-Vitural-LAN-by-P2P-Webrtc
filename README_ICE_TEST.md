# ICE Candidates Test Script (Non-Trickle Mode)

Script này được tạo để test việc gather ICE candidates một chiều sử dụng **non-trickle ICE** và kiểm tra xem client có nhận được candidates nào từ TURN server hay không.

## Non-Trickle ICE vs Trickle ICE

- **Trickle ICE**: Gửi candidates ngay khi tìm thấy (mặc định)
- **Non-Trickle ICE**: Chờ tất cả candidates được gather xong trước khi gửi offer

Script này sử dụng non-trickle ICE với `iceGatheringComplete` constraint.

## Cách sử dụng

### 1. Cài đặt dependencies

```bash
pip install -r requirements.txt
```

### 2. Cấu hình biến môi trường

Copy file `env.example` thành `.env` và cập nhật các giá trị:

```bash
cp env.example .env
```

Chỉnh sửa file `.env` với cấu hình TURN server của bạn:

```env
# Cấu hình cơ bản
AGENT_ID=ice-tester
PEER_ID=target-peer

# Cấu hình TURN server
ICE_URL=turn:your-turn-server.com:3478
ICE_USERNAME=your-username
ICE_CREDENTIAL=your-password
```

### 3. Chạy script test

```bash
python test_ice_candidates.py
```

## Cấu hình TURN Server

### Các loại TURN server được hỗ trợ:

1. **STUN servers** (miễn phí):

   ```env
   ICE_URLS=stun:stun.l.google.com:19302,stun:stun1.l.google.com:19302
   ```

2. **TURN servers** (cần authentication):

   ```env
   ICE_URL=turn:your-turn-server.com:3478
   ICE_USERNAME=your-username
   ICE_CREDENTIAL=your-password
   ```

3. **TURNS servers** (TLS encrypted):

   ```env
   ICE_URL=turns:your-turn-server.com:5349
   ICE_USERNAME=your-username
   ICE_CREDENTIAL=your-password
   ```

4. **Multiple servers**:
   ```env
   ICE_URLS=turn:turn1.example.com:3478,turn:turn2.example.com:3478,stun:stun.l.google.com:19302
   ```

### Ví dụ cấu hình cho các dịch vụ phổ biến:

#### Xirsys TURN Service

```env
ICE_URL=turn:global.xirsys.com:80
ICE_USERNAME=your-xirsys-username
ICE_CREDENTIAL=your-xirsys-credential
```

#### Twilio STUN/TURN Service

```env
ICE_URLS=stun:global.stun.twilio.com:3478,turn:global.turn.twilio.com:3478
ICE_USERNAME=your-twilio-username
ICE_CREDENTIAL=your-twilio-credential
```

#### Self-hosted Coturn

```env
ICE_URL=turn:your-domain.com:3478
ICE_USERNAME=your-turn-username
ICE_CREDENTIAL=your-turn-password
```

## Kết quả mong đợi

Script sẽ log các thông tin sau:

1. **ICE servers được cấu hình**
2. **ICE candidates nhận được** với thông tin chi tiết:

   - Type (host, srflx, relay, prflx)
   - Protocol (UDP, TCP)
   - Address và Port
   - Related Address (nếu có)

3. **Tóm tắt kết quả**:
   - Tổng số candidates nhận được
   - Phân loại theo type
   - Danh sách chi tiết tất cả candidates

### Ví dụ output thành công:

```
2024-01-15 10:30:00 - __main__ - INFO - ICE servers configured:
2024-01-15 10:30:00 - __main__ - INFO -   1. ['turn:your-turn-server.com:3478']
2024-01-15 10:30:00 - __main__ - INFO -      Username: your-username
2024-01-15 10:30:00 - __main__ - INFO - [ICE_CANDIDATE] candidate:1 1 UDP 2113667326 192.168.1.100 54400 typ host
2024-01-15 10:30:00 - __main__ - INFO -   Type: host
2024-01-15 10:30:00 - __main__ - INFO -   Protocol: UDP
2024-01-15 10:30:00 - __main__ - INFO -   Address: 192.168.1.100
2024-01-15 10:30:00 - __main__ - INFO -   Port: 54400
2024-01-15 10:30:00 - __main__ - INFO - [ICE_CANDIDATE] candidate:2 1 UDP 1694498815 203.0.113.1 54401 typ srflx raddr 192.168.1.100 rport 54400
2024-01-15 10:30:00 - __main__ - INFO -   Type: srflx
2024-01-15 10:30:00 - __main__ - INFO -   Protocol: UDP
2024-01-15 10:30:00 - __main__ - INFO -   Address: 203.0.113.1
2024-01-15 10:30:00 - __main__ - INFO -   Port: 54401
2024-01-15 10:30:00 - __main__ - INFO -   Related Address: 192.168.1.100
2024-01-15 10:30:00 - __main__ - INFO -   Related Port: 54400
2024-01-15 10:30:00 - __main__ - INFO - [ICE_CANDIDATE] candidate:3 1 UDP 16777215 203.0.113.2 3478 typ relay raddr 192.168.1.100 rport 54400
2024-01-15 10:30:00 - __main__ - INFO -   Type: relay
2024-01-15 10:30:00 - __main__ - INFO -   Protocol: UDP
2024-01-15 10:30:00 - __main__ - INFO -   Address: 203.0.113.2
2024-01-15 10:30:00 - __main__ - INFO -   Port: 3478
2024-01-15 10:30:00 - __main__ - INFO -   Related Address: 192.168.1.100
2024-01-15 10:30:00 - __main__ - INFO -   Related Port: 54400
2024-01-15 10:30:00 - __main__ - INFO - [END_OF_CANDIDATES] ICE gathering completed
2024-01-15 10:30:00 - __main__ - INFO -
2024-01-15 10:30:00 - __main__ - INFO - === ICE CANDIDATES SUMMARY ===
2024-01-15 10:30:00 - __main__ - INFO - Total candidates received: 3
2024-01-15 10:30:00 - __main__ - INFO -
2024-01-15 10:30:00 - __main__ - INFO - Candidates by type:
2024-01-15 10:30:00 - __main__ - INFO -   host: 1
2024-01-15 10:30:00 - __main__ - INFO -   srflx: 1
2024-01-15 10:30:00 - __main__ - INFO -   relay: 1
2024-01-15 10:30:00 - __main__ - INFO - ✅ Test PASSED: Received 3 ICE candidates
```

## Troubleshooting

### Không nhận được candidates:

- Kiểm tra cấu hình TURN server
- Kiểm tra username/password
- Kiểm tra firewall/network
- Thử với STUN servers trước

### Lỗi kết nối:

- Kiểm tra URL format
- Kiểm tra port accessibility
- Kiểm tra TLS certificate (cho TURNS)

### Timeout:

- Tăng timeout trong script
- Kiểm tra network connectivity
- Thử với servers khác
