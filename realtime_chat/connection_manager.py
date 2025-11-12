#!/usr/bin/env python3
"""
connection_manager.py

【処理概要】
WebSocket接続の管理を行うマネージャークラス。
クライアントの接続/切断、メタデータの管理を担当する。

【主な機能】
- クライアント接続の登録と削除
- WebSocketオブジェクトの保持
- ユーザー情報の管理（ID、名前、接続時刻）
- 接続状態の追跡
- スレッドセーフな操作（asyncio環境）

【実装内容】
1. クライアント情報をディクショナリで管理
2. ユニークIDの生成（UUID）
3. WebSocketオブジェクトとメタデータの紐付け
4. 接続/切断時の統計情報更新
5. クライアント検索機能
"""

import uuid
from typing import Dict, Optional, Set
from datetime import datetime
import asyncio


class ClientInfo:
    """
    クライアント情報を保持するクラス
    
    Attributes:
        client_id: クライアントの一意なID
        username: ユーザー名
        websocket: WebSocketオブジェクト
        connected_at: 接続時刻
        last_activity: 最終アクティビティ時刻
    """
    
    def __init__(self, client_id: str, username: str, websocket):
        self.client_id = client_id
        self.username = username
        self.websocket = websocket
        self.connected_at = datetime.now()
        self.last_activity = datetime.now()
    
    def update_activity(self):
        """最終アクティビティ時刻を更新"""
        self.last_activity = datetime.now()
    
    def __repr__(self):
        return f"<ClientInfo {self.username} ({self.client_id})>"


class ConnectionManager:
    """
    WebSocket接続を管理するマネージャー
    
    複数のクライアント接続を追跡し、各種操作を提供する。
    非同期環境で安全に動作する。
    """
    
    def __init__(self):
        """
        接続マネージャーの初期化
        
        内部的に以下のデータ構造を使用:
        - clients: client_id -> ClientInfo のマッピング
        - username_to_id: username -> client_id のマッピング（逆引き用）
        """
        self.clients: Dict[str, ClientInfo] = {}
        self.username_to_id: Dict[str, str] = {}
        self._lock = asyncio.Lock()  # 並行アクセス制御用
        
        # 統計情報
        self.total_connections = 0
        self.total_disconnections = 0
    
    async def register_client(self, websocket, username: str) -> str:
        """
        新しいクライアントを登録
        
        ユニークなIDを生成し、WebSocketオブジェクトと
        ユーザー情報を紐付ける。
        
        Args:
            websocket: WebSocketオブジェクト
            username: ユーザー名
        
        Returns:
            生成されたクライアントID
        """
        async with self._lock:
            # ユニークIDを生成
            client_id = str(uuid.uuid4())
            
            # ユーザー名の重複チェック（重複する場合は番号を付与）
            original_username = username
            counter = 1
            while username in self.username_to_id:
                username = f"{original_username}_{counter}"
                counter += 1
            
            # クライアント情報を作成
            client_info = ClientInfo(client_id, username, websocket)
            
            # 登録
            self.clients[client_id] = client_info
            self.username_to_id[username] = client_id
            
            # 統計更新
            self.total_connections += 1
            
            return client_id
    
    async def unregister_client(self, client_id: str):
        """
        クライアントを登録解除
        
        Args:
            client_id: クライアントID
        """
        async with self._lock:
            if client_id in self.clients:
                client_info = self.clients[client_id]
                
                # マッピングから削除
                del self.clients[client_id]
                if client_info.username in self.username_to_id:
                    del self.username_to_id[client_info.username]
                
                # 統計更新
                self.total_disconnections += 1
    
    def get_websocket(self, client_id: str):
        """
        クライアントIDからWebSocketオブジェクトを取得
        
        Args:
            client_id: クライアントID
        
        Returns:
            WebSocketオブジェクト（存在しない場合はNone）
        """
        client_info = self.clients.get(client_id)
        return client_info.websocket if client_info else None
    
    def get_username(self, client_id: str) -> str:
        """
        クライアントIDからユーザー名を取得
        
        Args:
            client_id: クライアントID
        
        Returns:
            ユーザー名（存在しない場合は"Unknown"）
        """
        client_info = self.clients.get(client_id)
        return client_info.username if client_info else "Unknown"
    
    def get_client_id_by_username(self, username: str) -> Optional[str]:
        """
        ユーザー名からクライアントIDを取得
        
        Args:
            username: ユーザー名
        
        Returns:
            クライアントID（存在しない場合はNone）
        """
        return self.username_to_id.get(username)
    
    def get_client_info(self, client_id: str) -> Optional[ClientInfo]:
        """
        クライアント情報を取得
        
        Args:
            client_id: クライアントID
        
        Returns:
            ClientInfoオブジェクト（存在しない場合はNone）
        """
        return self.clients.get(client_id)
    
    def update_activity(self, client_id: str):
        """
        クライアントのアクティビティ時刻を更新
        
        Args:
            client_id: クライアントID
        """
        client_info = self.clients.get(client_id)
        if client_info:
            client_info.update_activity()
    
    def get_all_clients(self) -> Dict[str, ClientInfo]:
        """
        全クライアント情報を取得
        
        Returns:
            client_id -> ClientInfo のディクショナリ
        """
        return self.clients.copy()
    
    def get_online_count(self) -> int:
        """
        現在オンラインのクライアント数を取得
        
        Returns:
            オンラインクライアント数
        """
        return len(self.clients)
    
    def get_all_usernames(self) -> Set[str]:
        """
        全ユーザー名のセットを取得
        
        Returns:
            ユーザー名のセット
        """
        return set(self.username_to_id.keys())
    
    def is_username_taken(self, username: str) -> bool:
        """
        ユーザー名が使用中かチェック
        
        Args:
            username: チェックするユーザー名
        
        Returns:
            使用中ならTrue、そうでなければFalse
        """
        return username in self.username_to_id
    
    def get_stats(self) -> Dict[str, int]:
        """
        統計情報を取得
        
        Returns:
            統計情報のディクショナリ
        """
        return {
            "online_clients": len(self.clients),
            "total_connections": self.total_connections,
            "total_disconnections": self.total_disconnections,
        }
    
    def __repr__(self):
        return f"<ConnectionManager: {len(self.clients)} clients online>"
