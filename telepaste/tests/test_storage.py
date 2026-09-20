import unittest
from unittest import mock

from telepaste.config import S3Config
from telepaste.storage import Uploader, UploadError


def config(**over):
    fields = dict(bucket="b", endpoint_url="https://cos.ap-beijing.myqcloud.com", region="ap-beijing",
                  access_key_id="k", secret_access_key="s",
                  public_base_url="https://img.example.com", prefix="clips", url_expire=600)
    fields.update(over)
    return S3Config(**fields)


class UploaderTests(unittest.TestCase):
    def test_keys_and_public_urls(self):
        up = Uploader(config(), client=mock.Mock())
        key = up.key_for("2026-09-17", "2026-09-17_120000_a b.png")
        self.assertEqual(key, "clips/2026-09-17/2026-09-17_120000_a b.png")
        self.assertEqual(up.url_for(key), "https://img.example.com/clips/2026-09-17/2026-09-17_120000_a%20b.png")
        self.assertEqual(Uploader(config(prefix=""), client=mock.Mock()).key_for("d", "f"), "d/f")

    def test_upload_calls_put_object(self):
        client = mock.Mock()
        up = Uploader(config(), client=client)
        url = up.upload(b"data", "clips/x.png", "image/png")
        client.put_object.assert_called_once_with(Bucket="b", Key="clips/x.png", Body=b"data",
                                                  ContentType="image/png")
        self.assertEqual(url, "https://img.example.com/clips/x.png")

    def test_presigned_when_no_public_base(self):
        client = mock.Mock()
        client.generate_presigned_url.return_value = "https://signed"
        up = Uploader(config(public_base_url=None), client=client)
        self.assertEqual(up.url_for("k"), "https://signed")
        client.generate_presigned_url.assert_called_once_with(
            "get_object", Params={"Bucket": "b", "Key": "k"}, ExpiresIn=600)

    def test_errors_are_wrapped_with_code_only(self):
        client = mock.Mock()
        exc = Exception("An error occurred (AccessDenied) ... secret stuff")
        exc.response = {"Error": {"Code": "AccessDenied", "Message": "secret stuff"}}
        client.put_object.side_effect = exc
        with self.assertRaises(UploadError) as cm:
            Uploader(config(), client=client).upload(b"d", "k", "image/png")
        self.assertEqual(str(cm.exception), "upload failed for k: AccessDenied")

    def test_describe(self):
        self.assertIn("presigned", Uploader(config(public_base_url=None), client=mock.Mock()).describe())
        self.assertIn("public", Uploader(config(), client=mock.Mock()).describe())


if __name__ == "__main__":
    unittest.main()
