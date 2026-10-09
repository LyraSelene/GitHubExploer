import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from core import Store, UserError
from desktop import Service, make_server
from media import import_character, media_file, media_state, select_character


class MediaTests(unittest.TestCase):
    def test_import_persists_and_http_only_serves_registered_media_with_ranges(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)/'data')
            source = Path(__file__).parent/'static'/'entrance.mp4'
            state = import_character(store, source)
            item = state['items'][0]
            select_character(store, item['id'])
            self.assertEqual(media_state(Store(store.directory))['selected'], item['id'])
            self.assertIsNone(media_file(store, '../research.sqlite3'))
            server=make_server(Service(store),'media-test')
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            base=f'http://127.0.0.1:{server.server_port}/media-test/media/'
            try:
                request=urllib.request.Request(base+item['id']+'.mp4',headers={'Range':'bytes=0-31'})
                with urllib.request.urlopen(request) as response:
                    self.assertEqual(response.status,206)
                    self.assertEqual(response.read(),source.read_bytes()[:32])
                with self.assertRaises(urllib.error.HTTPError): urllib.request.urlopen(base+'../research.sqlite3')
                with self.assertRaises(urllib.error.HTTPError): urllib.request.urlopen(base+'0'*32+'.mp4')
            finally:
                server.shutdown();server.server_close();worker.join(2)
            with self.assertRaises(UserError): select_character(store,'missing')
            select_character(store,'original')
            self.assertEqual(media_state(store)['selected'],'original')

    def test_fake_media_rejected_and_missing_asset_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'data')
            bad=Path(directory)/'fake.mp4';bad.write_text('not a video')
            with self.assertRaises(UserError): import_character(store,bad)
            self.assertEqual(media_state(store)['items'],[])
            state=import_character(store,Path(__file__).parent/'static'/'entrance.mp4')
            item=state['items'][0];select_character(store,item['id'])
            asset=media_file(store,item['id']+item['suffix']);asset.unlink()
            self.assertEqual(media_state(store)['selected'],'original')


if __name__=='__main__': unittest.main()
