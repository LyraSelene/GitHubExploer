"""User-selected character media copied to app storage, never arbitrary HTTP paths."""
import re
import shutil
import uuid
from pathlib import Path
from core import UserError

KINDS = {'.mp4': 'video', '.webm': 'video', '.gif': 'image', '.webp': 'image', '.png': 'image', '.jpg': 'image', '.jpeg': 'image'}


def media_state(store):
    items = store.get('character_media', [])
    selected = store.get('character_selected', 'original')
    valid = [item for item in items if isinstance(item, dict) and re.fullmatch(r'[a-f0-9]{32}', str(item.get('id', '')))
             and item.get('suffix') in KINDS and (store.directory/'media'/(item['id']+item['suffix'])).is_file()]
    if selected not in {item['id'] for item in valid}: selected = 'original'
    return {'items': valid, 'selected': selected}


def import_character(store, path):
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in KINDS: raise UserError('请选择 MP4 / WebM 视频、GIF 或图片。')
    size = path.stat().st_size
    if not 0 < size <= 100_000_000: raise UserError('每个动作素材最大 100 MB，且不能是空文件。')
    with path.open('rb') as file: signature = file.read(32)
    tests = {'.mp4': b'ftyp' in signature, '.webm': signature.startswith(b'\x1aE\xdf\xa3'),
             '.gif': signature.startswith((b'GIF87a', b'GIF89a')), '.png': signature.startswith(b'\x89PNG\r\n\x1a\n'),
             '.jpg': signature.startswith(b'\xff\xd8\xff'), '.jpeg': signature.startswith(b'\xff\xd8\xff'),
             '.webp': signature.startswith(b'RIFF') and b'WEBP' in signature}
    if not tests[suffix]: raise UserError('素材内容与扩展名不符，请选择真实视频或图片。')
    current = media_state(store)
    if len(current['items']) >= 40: raise UserError('动作库最多 40 个素材，请优先选择常用动作。')
    item = {'id': uuid.uuid4().hex, 'name': path.stem[:80], 'suffix': suffix, 'kind': KINDS[suffix], 'size': size}
    folder = store.directory/'media'; folder.mkdir(exist_ok=True)
    shutil.copyfile(path, folder/(item['id']+suffix))
    store.set('character_media', current['items']+[item])
    return media_state(store)


def select_character(store, selected):
    current = media_state(store)
    if selected != 'original' and selected not in {item['id'] for item in current['items']}:
        raise UserError('动作素材不存在，请重新导入或选择原画。')
    store.set('character_selected', selected)
    return media_state(store)


def media_file(store, identifier):
    current = media_state(store)
    for item in current['items']:
        if identifier == item['id'] + item['suffix']: return store.directory/'media'/identifier
    return None
