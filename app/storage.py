import io
import json
import os
import shutil
import time
import uuid
from abc import ABC, abstractmethod


def _new_id():
    return uuid.uuid4().hex


def _truncate(name, limit=255):
    return name[:limit] if name else "file"


class Storage(ABC):
    @abstractmethod
    def save(self, filename, fileobj, size=0):
        pass

    @abstractmethod
    def list_files(self):
        pass

    @abstractmethod
    def open_file(self, fid):
        pass

    @abstractmethod
    def delete_file(self, fid):
        pass


class LocalStorage(Storage):
    def __init__(self, root):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _dir(self, fid):
        return os.path.join(self.root, fid)

    def save(self, filename, fileobj, size=0):
        fid = _new_id()
        d = self._dir(fid)
        os.makedirs(d)
        dest = os.path.join(d, "blob")
        with open(dest, "wb") as out:
            while True:
                chunk = fileobj.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        meta = {
            "id": fid,
            "name": _truncate(filename),
            "size": os.stat(dest).st_size,
            "uploaded_at": time.time(),
        }
        with open(os.path.join(d, "meta.json"), "w") as f:
            json.dump(meta, f)
        return meta

    def list_files(self):
        out = []
        for entry in os.listdir(self.root):
            p = os.path.join(self.root, entry, "meta.json")
            if os.path.isfile(p):
                try:
                    with open(p) as f:
                        out.append(json.load(f))
                except (json.JSONDecodeError, OSError):
                    pass
        out.sort(key=lambda m: m.get("uploaded_at", 0), reverse=True)
        return out

    def open_file(self, fid):
        d = self._dir(fid)
        blob = os.path.join(d, "blob")
        if not os.path.isfile(blob):
            return None
        with open(os.path.join(d, "meta.json")) as f:
            meta = json.load(f)

        def chunks():
            with open(blob, "rb") as fh:
                while True:
                    c = fh.read(1024 * 1024)
                    if not c:
                        break
                    yield c

        return meta, chunks()

    def delete_file(self, fid):
        d = self._dir(fid)
        if os.path.isdir(d):
            shutil.rmtree(d)


class S3Storage(Storage):
    def __init__(self, endpoint, access_key, secret_key, bucket, region=None):
        import boto3

        self.bucket = bucket
        self.s3 = boto3.session.Session().client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region or "auto",
        )

    def _blob(self, fid):
        return f"{fid}.blob"

    def _meta(self, fid):
        return f"{fid}.meta.json"

    def save(self, filename, fileobj, size=0):
        fid = _new_id()
        self.s3.upload_fileobj(fileobj, self.bucket, self._blob(fid))
        head = self.s3.head_object(Bucket=self.bucket, Key=self._blob(fid))
        meta = {
            "id": fid,
            "name": _truncate(filename),
            "size": head["ContentLength"],
            "uploaded_at": time.time(),
        }
        self.s3.put_object(
            Bucket=self.bucket,
            Key=self._meta(fid),
            Body=json.dumps(meta).encode(),
            ContentType="application/json",
        )
        return meta

    def list_files(self):
        out = []
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith(".meta.json"):
                    try:
                        resp = self.s3.get_object(Bucket=self.bucket, Key=key)
                        out.append(json.loads(resp["Body"].read()))
                    except Exception:
                        pass
        out.sort(key=lambda m: m.get("uploaded_at", 0), reverse=True)
        return out

    def open_file(self, fid):
        try:
            resp = self.s3.get_object(Bucket=self.bucket, Key=self._blob(fid))
        except Exception:
            return None
        try:
            mresp = self.s3.get_object(Bucket=self.bucket, Key=self._meta(fid))
            meta = json.loads(mresp["Body"].read())
        except Exception:
            meta = {"id": fid, "name": fid, "size": 0, "uploaded_at": 0}
        body = resp["Body"]

        def chunks():
            while True:
                c = body.read(1024 * 1024)
                if not c:
                    break
                yield c

        return meta, chunks()

    def delete_file(self, fid):
        self.s3.delete_object(Bucket=self.bucket, Key=self._blob(fid))
        self.s3.delete_object(Bucket=self.bucket, Key=self._meta(fid))
