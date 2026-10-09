"""Local wallpaper preferences and portable image-to-video direction."""

MODES = {
    'living': {'name': '角色水流 · 持续动态', 'description': '人物、衣袖、发丝与水面共用缓慢水流，轻动作平滑融入；水波跟随画面。'},
    'calm': {'name': '水光日常', 'description': '轻微呼吸与稀疏水光，适合边学边看。'},
    'buoyant': {'name': '随水浮动', 'description': '原画随水轻轻起伏与摇摆，水波同节奏扩散；人物姿势不变。'},
    'float': {'name': '轻柔漂浮', 'description': '整张画面缓慢上下漂浮，人物姿势保持不变。'},
    'breathe': {'name': '呼吸节奏', 'description': '围绕人物缓慢缩放，让静画有安静的呼吸感。'},
    'drift': {'name': '镜头漫游', 'description': '镜头轻缓横移与推进，保留人物面部和左侧留白。'},
    'ripple': {'name': '水波涟漪', 'description': '右侧水面叠加柔和扩散的涟漪，原画不被扭曲。'},
    'sparkle': {'name': '星屑水光', 'description': '细小光点与星芒随水光漂动。'},
    'still': {'name': '静态原画', 'description': '关闭循环动态，保留原始壁纸。'},
}
ENTRIES = {'portrait': '原画蓝光描边 · 同姿势入场', 'outline': '参考视频 · 旧入场', 'tide': '水光入场', 'mist': '薄雾渐显', 'fade': '柔和淡入', 'none': '不播放'}
WATER_PROMPT = """用途：Windows 学习应用的入场视频。使用上传原图作为人物身份、服饰、画风与最终构图的参考，不生成界面文字。

时长：6 秒，横向 16:9，镜头稳定，柔和浅蓝色水面与二次元插画质感。
0–1.5 秒：水面先呈现轻薄蓝白雾光，细小光点缓慢浮起，左侧保持干净留白。
1.5–4 秒：雾光逐渐散开，原图人物和水面自然显现；镜头极轻地推近，人物仅随水面做微小漂浮，发丝末端、裙摆边缘与水光轻缓摆动。不要挥手、转身或改变身体姿势。
4–6 秒：镜头与人物逐渐停稳，水波柔和扩散；最后一帧精确贴近原图的构图与色彩，方便切换到应用壁纸。

保持：同一人物的面部、蓝色长发、服饰、手部数量与姿态、右侧位置；左侧约 45% 区域低对比留白，适合叠加界面。仅使用参考图已有元素。
避免：人物变脸、肢体变形、多指或重复手臂、大幅身体运动、镜头抖动、闪烁、快速缩放、额外角色、文字、水印、把界面卡片画进视频。
声音：无音轨。整体清澈、安静，运动幅度很小。
"""
PROMPT = """用途：Windows 学习应用的蓝色荧光轮廓描边入场动画。输入原画是唯一的人物身份、构图、姿势、比例、服饰和视角参考，不生成新姿势或新肢体。

时长：约 8.2 秒，横向 16:9，固定镜头，无音轨。
0–0.4 秒：深色背景，人物本体几乎不可见，仅保留极少量低亮度蓝色环境光。
0.4–6.2 秒：一条细而清晰的蓝白色发光线从头部开始，像光笔沿真实原画路径逐段生长，依次勾勒头部、发丝、脸部轮廓、肩膀、手臂、衣服、裙摆和身体边缘。每条轮廓有明确起点和方向，前一段完成后再进入下一段，不能所有线条同时出现。
6.0–7.6 秒：轮廓基本完成后，人物内部颜色、五官和服装细节从轮廓内部平滑淡入；描边保持细窄、稳定、边缘清晰，只有小范围柔和蓝光，不出现白雾、粗重霓虹或强闪烁。
7.2–8.2 秒：蓝色线条亮度逐渐减弱并融入原画，最后一帧精确回到输入原画。水面、头发和衣服只保留极轻微光线流动。

严格保持：原画人物的脸型、眼睛位置、表情、蓝色长发、服饰、手部数量、身体姿势、比例、视角、画面位置和左侧留白。不要挥手、转身、眨眼、微笑、改变姿势、添加角色、字幕、Logo、水印、镜头抖动或快速缩放。整体节奏平滑、克制、精致，像蓝色光笔在黑暗中逐笔绘制插画。

此提示词只用于外部图生视频工具；App 默认使用本地原画路径描边并接续到主页，不依据文本生成新的角色。
"""
DEFAULT = {'mode': 'living', 'intensity': 70, 'paused': False, 'cycle': False,
           'entry': 'portrait', 'entry_enabled': True, 'prompt': PROMPT, 'auto_actions': True,
           'tail_amplitude':75, 'tail_duration':5.2, 'water_preset':'quiet',
           'water_wait_min':20, 'water_wait_max':45, 'water_tail':True,
           'water_brush':True, 'water_fin':True, 'water_drift':True, 'water_respond':True}


def validate_preferences(values):
    from core import UserError
    if not isinstance(values, dict):
        raise UserError('动态设置格式无效。')
    prefs = {**DEFAULT, **{k: v for k, v in values.items() if k in DEFAULT}}
    if not isinstance(prefs['mode'], str) or not isinstance(prefs['entry'], str) or prefs['mode'] not in MODES or prefs['entry'] not in ENTRIES:
        raise UserError('请选择支持的动态或入场模式。')
    if isinstance(prefs['intensity'], bool) or not isinstance(prefs['intensity'], int) or not 0 <= prefs['intensity'] <= 100:
        raise UserError('动态强度应为 0–100 的整数。')
    for key in ['paused', 'cycle', 'entry_enabled', 'auto_actions','water_tail','water_brush','water_fin','water_drift','water_respond']:
        if not isinstance(prefs[key], bool):
            raise UserError('动态开关格式无效。')
    if type(prefs['tail_amplitude']) is not int or not 0 <= prefs['tail_amplitude'] <= 100:
        raise UserError('摆尾幅度应为0–100的整数。')
    if type(prefs['tail_duration']) not in (int, float) or not 4 <= prefs['tail_duration'] <= 6:
        raise UserError('摆尾时长应为4–6秒。')
    if prefs['water_preset'] not in ('quiet','lively'):
        raise UserError('请选择安静或活泼预设。')
    if any(type(prefs[k]) is not int for k in ('water_wait_min','water_wait_max')) or not 8 <= prefs['water_wait_min'] <= prefs['water_wait_max'] <= 180:
        raise UserError('随机等待时间应为8–180秒，最大值不能小于最小值。')
    if not isinstance(prefs['prompt'], str) or len(prefs['prompt']) > 12_000:
        raise UserError('提示词最多 12,000 字符。')
    return prefs


def load_preferences(store):
    from core import UserError
    try:
        values = store.get('wallpaper_motion', {})
        if not store.get('portrait_scene_v1', False):
            # Apply the corrected same-pose entrance and continuous local motion once.
            if isinstance(values, dict):
                values = {**values, 'entry': 'portrait', 'mode': 'living', 'paused': False, 'intensity': 70, 'cycle': False}
                if values.get('prompt') == WATER_PROMPT: values['prompt'] = PROMPT
                store.set('wallpaper_motion', values)
            store.set('character_selected', 'original')
            store.set('portrait_scene_v1', True)
        return validate_preferences(values)
    except (UserError, TypeError):
        return dict(DEFAULT)
