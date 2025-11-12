#!/usr/bin/env python3
"""
room_manager.py

【処理概要】
チャットルームの管理を行うマネージャークラス。
ルームへの参加/退出、メンバー管理を担当する。

【主な機能】
- ルームの作成と削除
- ユーザーのルーム参加/退出
- ルームメンバーの追跡
- ルーム一覧の取得
- 空ルームの自動削除

【実装内容】
1. ルームごとにメンバーセットを管理
2. ユーザーごとに参加ルームセットを管理（双方向マッピング）
3. ルーム作成時のメタデータ設定
4. 空ルーム検出と自動削除
5. スレッドセーフな操作
"""

from typing import Dict, Set, Optional, List
from datetime import datetime
from collections import defaultdict
import asyncio


class RoomInfo:
    """
    ルーム情報を保持するクラス
    
    Attributes:
        name: ルーム名
        created_at: 作成時刻
        members: ルームメンバーのクライアントIDセット
        message_count: メッセージ総数（統計用）
    """
    
    def __init__(self, name: str):
        self.name = name
        self.created_at = datetime.now()
        self.members: Set[str] = set()
        self.message_count = 0
    
    def add_member(self, client_id: str):
        """メンバーを追加"""
        self.members.add(client_id)
    
    def remove_member(self, client_id: str):
        """メンバーを削除"""
        self.members.discard(client_id)
    
    def is_empty(self) -> bool:
        """ルームが空か確認"""
        return len(self.members) == 0
    
    def increment_message_count(self):
        """メッセージカウントを増加"""
        self.message_count += 1
    
    def __repr__(self):
        return f"<RoomInfo '{self.name}' ({len(self.members)} members)>"


class RoomManager:
    """
    チャットルームを管理するマネージャー
    
    複数のルームとそのメンバーを追跡し、
    ルーム操作の各種メソッドを提供する。
    """
    
    def __init__(self):
        """
        ルームマネージャーの初期化
        
        内部データ構造:
        - rooms: room_name -> RoomInfo のマッピング
        - user_rooms: client_id -> 参加ルームのセット
        """
        self.rooms: Dict[str, RoomInfo] = {}
        self.user_rooms: Dict[str, Set[str]] = defaultdict(set)
        self._lock = asyncio.Lock()
        
        # デフォルトルームを作成
        self._create_default_rooms()
    
    def _create_default_rooms(self):
        """
        デフォルトのルームを作成
        
        システム起動時に基本的なルームを用意する。
        """
        default_rooms = ["general", "random", "help"]
        
        for room_name in default_rooms:
            self.rooms[room_name] = RoomInfo(room_name)
    
    async def join_room(self, client_id: str, room_name: str):
        """
        ユーザーをルームに参加させる
        
        ルームが存在しない場合は自動的に作成する。
        
        Args:
            client_id: クライアントID
            room_name: ルーム名
        """
        async with self._lock:
            # ルームが存在しない場合は作成
            if room_name not in self.rooms:
                self.rooms[room_name] = RoomInfo(room_name)
            
            # メンバーとして追加
            room_info = self.rooms[room_name]
            room_info.add_member(client_id)
            
            # ユーザーの参加ルームに追加
            self.user_rooms[client_id].add(room_name)
    
    async def leave_room(self, client_id: str, room_name: str):
        """
        ユーザーをルームから退出させる
        
        ルームが空になった場合は自動的に削除する
        （デフォルトルームを除く）。
        
        Args:
            client_id: クライアントID
            room_name: ルーム名
        """
        async with self._lock:
            if room_name not in self.rooms:
                return
            
            room_info = self.rooms[room_name]
            room_info.remove_member(client_id)
            
            # ユーザーの参加ルームから削除
            self.user_rooms[client_id].discard(room_name)
            
            # 空になったら削除（デフォルトルーム以外）
            if room_info.is_empty() and not self._is_default_room(room_name):
                del self.rooms[room_name]
    
    async def leave_all_rooms(self, client_id: str):
        """
        ユーザーを全ルームから退出させる
        
        Args:
            client_id: クライアントID
        """
        rooms = self.get_user_rooms(client_id).copy()
        
        for room_name in rooms:
            await self.leave_room(client_id, room_name)
        
        # ユーザー情報をクリーンアップ
        if client_id in self.user_rooms:
            del self.user_rooms[client_id]
    
    def get_room_members(self, room_name: str) -> Set[str]:
        """
        ルームのメンバー一覧を取得
        
        Args:
            room_name: ルーム名
        
        Returns:
            メンバーのクライアントIDセット
        """
        room_info = self.rooms.get(room_name)
        return room_info.members.copy() if room_info else set()
    
    def get_user_rooms(self, client_id: str) -> Set[str]:
        """
        ユーザーが参加しているルーム一覧を取得
        
        Args:
            client_id: クライアントID
        
        Returns:
            参加ルーム名のセット
        """
        return self.user_rooms.get(client_id, set()).copy()
    
    def get_all_rooms(self) -> List[str]:
        """
        全ルーム名のリストを取得
        
        Returns:
            ルーム名のリスト
        """
        return list(self.rooms.keys())
    
    def get_room_info(self, room_name: str) -> Optional[RoomInfo]:
        """
        ルーム情報を取得
        
        Args:
            room_name: ルーム名
        
        Returns:
            RoomInfoオブジェクト（存在しない場合はNone）
        """
        return self.rooms.get(room_name)
    
    def room_exists(self, room_name: str) -> bool:
        """
        ルームが存在するか確認
        
        Args:
            room_name: ルーム名
        
        Returns:
            存在すればTrue、そうでなければFalse
        """
        return room_name in self.rooms
    
    def is_user_in_room(self, client_id: str, room_name: str) -> bool:
        """
        ユーザーがルームに参加しているか確認
        
        Args:
            client_id: クライアントID
            room_name: ルーム名
        
        Returns:
            参加していればTrue、そうでなければFalse
        """
        return room_name in self.user_rooms.get(client_id, set())
    
    def get_room_count(self) -> int:
        """
        総ルーム数を取得
        
        Returns:
            ルーム数
        """
        return len(self.rooms)
    
    def get_total_members_count(self) -> int:
        """
        全ルームの総メンバー数を取得（重複カウント）
        
        Returns:
            総メンバー数
        """
        return sum(len(room.members) for room in self.rooms.values())
    
    def increment_message_count(self, room_name: str):
        """
        ルームのメッセージカウントを増加
        
        Args:
            room_name: ルーム名
        """
        room_info = self.rooms.get(room_name)
        if room_info:
            room_info.increment_message_count()
    
    def get_room_stats(self, room_name: str) -> Optional[Dict]:
        """
        ルームの統計情報を取得
        
        Args:
            room_name: ルーム名
        
        Returns:
            統計情報のディクショナリ
        """
        room_info = self.rooms.get(room_name)
        
        if not room_info:
            return None
        
        return {
            "name": room_info.name,
            "created_at": room_info.created_at.isoformat(),
            "member_count": len(room_info.members),
            "message_count": room_info.message_count,
        }
    
    def get_all_stats(self) -> Dict:
        """
        全ルームの統計情報を取得
        
        Returns:
            統計情報のディクショナリ
        """
        return {
            "total_rooms": len(self.rooms),
            "total_members": self.get_total_members_count(),
            "rooms": {
                name: self.get_room_stats(name)
                for name in self.rooms.keys()
            }
        }
    
    def _is_default_room(self, room_name: str) -> bool:
        """
        デフォルトルームか確認
        
        Args:
            room_name: ルーム名
        
        Returns:
            デフォルトルームならTrue
        """
        default_rooms = {"general", "random", "help"}
        return room_name in default_rooms
    
    async def cleanup_empty_rooms(self):
        """
        空のルームを削除（デフォルトルーム除く）
        
        定期実行する想定。
        """
        async with self._lock:
            rooms_to_delete = [
                room_name
                for room_name, room_info in self.rooms.items()
                if room_info.is_empty() and not self._is_default_room(room_name)
            ]
            
            for room_name in rooms_to_delete:
                del self.rooms[room_name]
            
            return len(rooms_to_delete)
    
    def __repr__(self):
        return f"<RoomManager: {len(self.rooms)} rooms, {self.get_total_members_count()} total members>"
