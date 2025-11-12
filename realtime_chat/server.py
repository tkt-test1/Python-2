#!/usr/bin/env python3
"""
server.py

【処理概要】
WebSocketベースのリアルタイムチャットサーバー。
非同期処理でクライアント接続を管理し、メッセージをリアルタイムで配信する。

【主な機能】
- WebSocket接続の受け入れと管理
- メッセージのルーティングとブロードキャスト
- ユーザー認証とセッション管理
- プレゼンス情報の管理（オンライン/入力中）
- エラーハンドリングと接続監視

【実装内容】
1. WebSocketサーバーの起動
2. クライアント接続時の認証処理
3. メッセージ受信とコマンド解析
4. ルームへのメッセージブロードキャスト
5. 接続/切断の通知
6. ハートビート（接続維持）の処理
"""

import asyncio
import websockets
import json
import logging
from typing import Set, Dict, Any
from datetime import datetime
from connection_manager import ConnectionManager
from room_manager import RoomManager

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class ChatServer:
    """
    リアルタイムチャットサーバー
    
    WebSocket接続を管理し、メッセージをルーティングする。
    複数のチャットルームとユーザープレゼンスをサポート。
    """
    
    def __init__(self, host: str = "localhost", port: int = 8765):
        """
        サーバーの初期化
        
        Args:
            host: バインドするホスト名
            port: ポート番号
        """
        self.host = host
        self.port = port
        self.connection_manager = ConnectionManager()
        self.room_manager = RoomManager()
        
        logger.info(f"🚀 Chat server initialized on {host}:{port}")
    
    async def handle_client(self, websocket, path: str):
        """
        クライアント接続のメインハンドラ
        
        接続ライフサイクル全体を管理:
        1. 接続受け入れ
        2. 認証処理
        3. メッセージループ
        4. 切断処理
        
        Args:
            websocket: WebSocketオブジェクト
            path: 接続パス
        """
        client_id = None
        
        try:
            # 認証処理（最初のメッセージでユーザー名を受け取る）
            auth_message = await websocket.recv()
            auth_data = json.loads(auth_message)
            
            if auth_data.get("type") != "auth":
                await self._send_error(websocket, "First message must be authentication")
                return
            
            username = auth_data.get("username", "Anonymous")
            client_id = await self.connection_manager.register_client(websocket, username)
            
            logger.info(f"✅ Client connected: {username} (ID: {client_id})")
            
            # ウェルカムメッセージ送信
            await self._send_welcome(websocket, client_id, username)
            
            # デフォルトルームに参加
            default_room = "general"
            await self.room_manager.join_room(client_id, default_room)
            await self._broadcast_presence(client_id, "online", default_room)
            
            # メッセージ受信ループ
            async for message in websocket:
                await self._handle_message(client_id, message)
        
        except websockets.exceptions.ConnectionClosedOK:
            logger.info(f"📴 Client disconnected gracefully: {client_id}")
        
        except websockets.exceptions.ConnectionClosedError as e:
            logger.warning(f"⚠️  Client disconnected with error: {client_id} - {e}")
        
        except Exception as e:
            logger.error(f"❌ Error handling client {client_id}: {e}", exc_info=True)
        
        finally:
            # クライアント切断処理
            if client_id:
                await self._handle_disconnect(client_id)
    
    async def _handle_message(self, client_id: str, message: str):
        """
        クライアントからのメッセージを処理
        
        メッセージタイプに応じて適切なハンドラを呼び出す:
        - chat: チャットメッセージ
        - typing: 入力中通知
        - join_room: ルーム参加
        - leave_room: ルーム退出
        - ping: ハートビート
        
        Args:
            client_id: クライアントID
            message: 受信したメッセージ（JSON文字列）
        """
        try:
            data = json.loads(message)
            msg_type = data.get("type")
            
            # メッセージタイプ別の処理
            if msg_type == "chat":
                await self._handle_chat_message(client_id, data)
            
            elif msg_type == "typing":
                await self._handle_typing(client_id, data)
            
            elif msg_type == "join_room":
                await self._handle_join_room(client_id, data)
            
            elif msg_type == "leave_room":
                await self._handle_leave_room(client_id, data)
            
            elif msg_type == "ping":
                await self._handle_ping(client_id)
            
            else:
                logger.warning(f"⚠️  Unknown message type: {msg_type} from {client_id}")
        
        except json.JSONDecodeError:
            logger.error(f"❌ Invalid JSON from {client_id}: {message}")
            websocket = self.connection_manager.get_websocket(client_id)
            if websocket:
                await self._send_error(websocket, "Invalid JSON format")
        
        except Exception as e:
            logger.error(f"❌ Error processing message from {client_id}: {e}")
    
    async def _handle_chat_message(self, client_id: str, data: Dict[str, Any]):
        """
        チャットメッセージをルームにブロードキャスト
        
        Args:
            client_id: 送信者のクライアントID
            data: メッセージデータ
        """
        room = data.get("room", "general")
        content = data.get("content", "")
        
        if not content.strip():
            return
        
        username = self.connection_manager.get_username(client_id)
        
        # メッセージを構築
        message = {
            "type": "message",
            "room": room,
            "sender": username,
            "sender_id": client_id,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        
        # ルームにブロードキャスト
        await self._broadcast_to_room(room, message, exclude=None)
        
        logger.info(f"💬 [{room}] {username}: {content[:50]}...")
    
    async def _handle_typing(self, client_id: str, data: Dict[str, Any]):
        """
        入力中状態をルームにブロードキャスト
        
        Args:
            client_id: クライアントID
            data: 入力中データ
        """
        room = data.get("room", "general")
        is_typing = data.get("is_typing", False)
        username = self.connection_manager.get_username(client_id)
        
        typing_message = {
            "type": "typing",
            "room": room,
            "user": username,
            "user_id": client_id,
            "is_typing": is_typing
        }
        
        # 自分以外にブロードキャスト
        await self._broadcast_to_room(room, typing_message, exclude=client_id)
    
    async def _handle_join_room(self, client_id: str, data: Dict[str, Any]):
        """
        ルーム参加処理
        
        Args:
            client_id: クライアントID
            data: ルーム参加データ
        """
        room = data.get("room")
        
        if not room:
            return
        
        await self.room_manager.join_room(client_id, room)
        username = self.connection_manager.get_username(client_id)
        
        # ルームメンバーに通知
        join_message = {
            "type": "user_joined",
            "room": room,
            "user": username,
            "user_id": client_id,
            "timestamp": datetime.now().isoformat()
        }
        
        await self._broadcast_to_room(room, join_message, exclude=None)
        
        # 参加者にルーム情報を送信
        await self._send_room_info(client_id, room)
        
        logger.info(f"👋 {username} joined room: {room}")
    
    async def _handle_leave_room(self, client_id: str, data: Dict[str, Any]):
        """
        ルーム退出処理
        
        Args:
            client_id: クライアントID
            data: ルーム退出データ
        """
        room = data.get("room")
        
        if not room:
            return
        
        username = self.connection_manager.get_username(client_id)
        await self.room_manager.leave_room(client_id, room)
        
        # ルームメンバーに通知
        leave_message = {
            "type": "user_left",
            "room": room,
            "user": username,
            "user_id": client_id,
            "timestamp": datetime.now().isoformat()
        }
        
        await self._broadcast_to_room(room, leave_message, exclude=None)
        
        logger.info(f"👋 {username} left room: {room}")
    
    async def _handle_ping(self, client_id: str):
        """
        ハートビート（Ping）に応答
        
        Args:
            client_id: クライアントID
        """
        websocket = self.connection_manager.get_websocket(client_id)
        if websocket:
            pong_message = {
                "type": "pong",
                "timestamp": datetime.now().isoformat()
            }
            await websocket.send(json.dumps(pong_message))
    
    async def _handle_disconnect(self, client_id: str):
        """
        クライアント切断時の処理
        
        Args:
            client_id: クライアントID
        """
        username = self.connection_manager.get_username(client_id)
        rooms = self.room_manager.get_user_rooms(client_id)
        
        # 全ルームから退出
        for room in rooms:
            await self.room_manager.leave_room(client_id, room)
            
            # オフライン通知
            offline_message = {
                "type": "presence",
                "room": room,
                "user": username,
                "user_id": client_id,
                "status": "offline",
                "timestamp": datetime.now().isoformat()
            }
            
            await self._broadcast_to_room(room, offline_message, exclude=None)
        
        # 接続マネージャーから削除
        await self.connection_manager.unregister_client(client_id)
        
        logger.info(f"🔌 Client fully disconnected: {username} (ID: {client_id})")
    
    async def _broadcast_to_room(self, room: str, message: Dict[str, Any], exclude: str = None):
        """
        ルーム内の全クライアントにメッセージをブロードキャスト
        
        Args:
            room: ルーム名
            message: 送信するメッセージ
            exclude: 除外するクライアントID（Noneなら全員に送信）
        """
        members = self.room_manager.get_room_members(room)
        message_json = json.dumps(message)
        
        tasks = []
        for member_id in members:
            if member_id == exclude:
                continue
            
            websocket = self.connection_manager.get_websocket(member_id)
            if websocket:
                tasks.append(websocket.send(message_json))
        
        # 並列送信
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _broadcast_presence(self, client_id: str, status: str, room: str):
        """
        プレゼンス状態をブロードキャスト
        
        Args:
            client_id: クライアントID
            status: ステータス（online/offline/away）
            room: ルーム名
        """
        username = self.connection_manager.get_username(client_id)
        
        presence_message = {
            "type": "presence",
            "room": room,
            "user": username,
            "user_id": client_id,
            "status": status,
            "timestamp": datetime.now().isoformat()
        }
        
        await self._broadcast_to_room(room, presence_message, exclude=client_id)
    
    async def _send_welcome(self, websocket, client_id: str, username: str):
        """
        ウェルカムメッセージを送信
        
        Args:
            websocket: WebSocketオブジェクト
            client_id: クライアントID
            username: ユーザー名
        """
        welcome = {
            "type": "welcome",
            "client_id": client_id,
            "username": username,
            "message": "Welcome to the chat server!",
            "timestamp": datetime.now().isoformat()
        }
        await websocket.send(json.dumps(welcome))
    
    async def _send_room_info(self, client_id: str, room: str):
        """
        ルーム情報を送信
        
        Args:
            client_id: クライアントID
            room: ルーム名
        """
        members = self.room_manager.get_room_members(room)
        member_names = [
            self.connection_manager.get_username(mid) for mid in members
        ]
        
        room_info = {
            "type": "room_info",
            "room": room,
            "members": member_names,
            "member_count": len(members)
        }
        
        websocket = self.connection_manager.get_websocket(client_id)
        if websocket:
            await websocket.send(json.dumps(room_info))
    
    async def _send_error(self, websocket, error_message: str):
        """
        エラーメッセージを送信
        
        Args:
            websocket: WebSocketオブジェクト
            error_message: エラーメッセージ
        """
        error = {
            "type": "error",
            "message": error_message,
            "timestamp": datetime.now().isoformat()
        }
        await websocket.send(json.dumps(error))
    
    async def start(self):
        """
        サーバーを起動
        
        WebSocketサーバーを起動し、接続を待ち受ける。
        """
        logger.info("=" * 60)
        logger.info("🚀 Starting WebSocket Chat Server")
        logger.info(f"📡 Listening on ws://{self.host}:{self.port}")
        logger.info("=" * 60)
        
        async with websockets.serve(self.handle_client, self.host, self.port):
            await asyncio.Future()  # 永遠に実行


async def main():
    """メイン関数"""
    server = ChatServer(host="localhost", port=8765)
    await server.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 Server shutting down...")
