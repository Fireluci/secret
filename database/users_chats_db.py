import motor.motor_asyncio
from datetime import datetime, timedelta

from info import DATABASE_NAME, DATABASE_URI


class Database:
    def __init__(self, uri, database_name):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self._client[database_name]
        self.col = self.db.users
        self.grp = self.db.groups
        self.cache = self.db.bot_cache

    def new_user(self, id, name):
        return {
            "id": int(id),
            "name": name,
            "ban_status": {"is_banned": False, "ban_reason": ""},
        }

    async def add_user(self, id, name):
        await self.col.update_one(
            {"id": int(id)},
            {"$setOnInsert": self.new_user(id, name)},
            upsert=True,
        )

    async def is_user_exist(self, id):
        return bool(await self.col.find_one({"id": int(id)}, {"_id": 1}))

    async def total_users_count(self):
        return await self.col.count_documents({})

    async def remove_ban(self, id):
        await self.col.update_one(
            {"id": int(id)},
            {"$set": {"ban_status": {"is_banned": False, "ban_reason": ""}}},
        )

    async def ban_user(self, user_id, ban_reason="No Reason"):
        await self.col.update_one(
            {"id": int(user_id)},
            {"$set": {"ban_status": {"is_banned": True, "ban_reason": ban_reason}}},
        )

    async def get_ban_status(self, id):
        default = {"is_banned": False, "ban_reason": ""}
        user = await self.col.find_one({"id": int(id)})
        return user.get("ban_status", default) if user else default

    async def get_all_users(self):
        return self.col.find({})

    async def delete_user(self, user_id):
        await self.col.delete_many({"id": int(user_id)})

    async def get_banned_users(self):
        cursor = self.col.find({"ban_status.is_banned": True}, {"id": 1})
        return [user["id"] async for user in cursor]

    async def connect_group(self, chat_id, title):
        await self.grp.update_one(
            {"id": int(chat_id)},
            {
                "$set": {"title": title, "connected": True},
                "$setOnInsert": {"settings": {}},
            },
            upsert=True,
        )

    async def disconnect_group(self, chat_id):
        await self.grp.update_one(
            {"id": int(chat_id)},
            {"$set": {"connected": False}},
            upsert=True,
        )

    async def is_group_connected(self, chat_id):
        group = await self.grp.find_one({"id": int(chat_id)}, {"connected": 1})
        return bool(group and group.get("connected") is True)

    async def get_group_settings(self, chat_id):
        group = await self.grp.find_one({"id": int(chat_id)}, {"settings": 1})
        return group.get("settings", {}) if group else {}

    async def set_group_setting(self, chat_id, key, value):
        await self.grp.update_one(
            {"id": int(chat_id)},
            {"$set": {f"settings.{key}": value}},
            upsert=True,
        )

    async def remove_group_setting(self, chat_id, key):
        await self.grp.update_one(
            {"id": int(chat_id)},
            {"$unset": {f"settings.{key}": ""}},
            upsert=True,
        )

    async def total_chat_count(self):
        return await self.grp.count_documents({"connected": True})

    async def get_all_chats(self):
        return self.grp.find({"connected": True})

    async def ensure_cache_indexes(self):
        await self.cache.create_index(
            "expires_at",
            expireAfterSeconds=0,
        )

    async def set_cache(self, key, data, ttl=600):
        await self.cache.update_one(
            {"_id": key},
            {
                "$set": {
                    "data": data,
                    "expires_at": datetime.utcnow() + timedelta(seconds=ttl),
                }
            },
            upsert=True,
        )

    async def get_cache(self, key):
        item = await self.cache.find_one({"_id": key})
        if not item:
            return None
        if item.get("expires_at") and item["expires_at"] <= datetime.utcnow():
            await self.cache.delete_one({"_id": key})
            return None
        return item.get("data")

    async def delete_cache(self, key):
        await self.cache.delete_one({"_id": key})

    async def set_restart_flag(self):
        await self.set_cache("__manual_restart__", {"restart": True}, ttl=600)

    async def consume_restart_flag(self):
        data = await self.get_cache("__manual_restart__")
        if data:
            await self.delete_cache("__manual_restart__")
            return True
        return False

    async def get_db_size(self):
        return (await self.db.command("dbstats"))["dataSize"]


db = Database(DATABASE_URI, DATABASE_NAME)
