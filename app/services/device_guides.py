"""在售设备的可追溯参数摘要与安全快速上手建议。"""
from __future__ import annotations


DEVICE_PROFILES = {
    "R10": {
        "summary": "约2420万像素 APS-C 可换镜头微单，对焦响应快，适合人像、宠物和活动抓拍。",
        "quick_start": ["装好镜头和存储卡再开机", "新手先用A+或Av模式", "开启人物/动物眼部检测"],
        "setting_tips": ["室内抓拍可从1/500秒、自动ISO开始", "人像优先使用单点或眼部追焦"],
        "guide_url": "https://www.canon.com.cn/product/r10/",
        "strengths": "追焦、可换镜头、活动抓拍",
    },
    "G7X2": {
        "summary": "约2010万像素大尺寸CMOS便携相机，24-100mm等效焦段和F1.8-2.8镜头兼顾旅行与人像。",
        "quick_start": ["插卡并确认电量", "新手使用AUTO模式", "自拍时翻转屏幕并开启人脸对焦"],
        "setting_tips": ["夜景尽量靠稳并开启防抖", "人像使用广角端时避免距离面部过近"],
        "guide_url": "https://www.canon.com.cn/product/g7xmk2/",
        "strengths": "轻便、自拍、旅行记录",
    },
    "XM5": {
        "summary": "约2610万像素 APS-C 微单，机身轻巧并支持主体识别，适合旅行、视频和人像。",
        "quick_start": ["确认镜头卡口锁定", "新手先选自动模式和人脸/眼部检测", "视频前检查存储卡余量"],
        "setting_tips": ["运动主体优先连续对焦", "室内人像搭配18-50mm F2.8更从容"],
        "guide_url": "https://www.fujifilm-x.com/zh-cn/products/cameras/x-m5/",
        "strengths": "色彩、轻便、照片视频兼顾",
    },
    "POCKET3": {
        "summary": "轻量手持云台相机，三轴机械增稳，适合Vlog、走拍和短视频记录。",
        "quick_start": ["开机后等待云台自检完成", "握持时不要强行掰动云台", "拍摄前确认microSD卡空间"],
        "setting_tips": ["走拍使用跟随模式", "快速运动可提高快门并保证环境光线"],
        "guide_url": "https://www.dji.com/cn/osmo-pocket-3",
        "strengths": "视频防抖、走拍、Vlog",
    },
    "FLIP": {
        "summary": "轻量航拍设备，适合合规环境下的旅行航拍；起飞前必须确认当地禁飞和实名要求。",
        "quick_start": ["检查桨叶与电池卡扣", "更新禁飞区数据", "只在视距内和允许区域飞行"],
        "setting_tips": ["避免大风、雨雪和人群上空", "电量不足时及时返航"],
        "guide_url": "https://www.dji.com/cn/flip",
        "strengths": "旅行航拍、自动跟拍",
    },
}

_RETRO_IDS = {"G12", "A620", "IXUS110", "U300", "U400", "U1"}


def profile_for(camera_id: str) -> dict:
    if camera_id in DEVICE_PROFILES:
        return DEVICE_PROFILES[camera_id]
    if camera_id in _RETRO_IDS:
        return {
            "summary": "复古便携数码相机，适合日常记录和氛围感直出；具体功能以实机菜单为准。",
            "quick_start": ["装好电池和存储卡", "先用自动模式试拍", "拍摄后放大检查是否清晰"],
            "setting_tips": ["光线不足时尽量靠稳", "重要拍摄请提前试机并准备备用电池"],
            "guide_url": None,
            "strengths": "复古氛围、轻便、日常记录",
        }
    return {
        "summary": "适合按实际场景试拍后确定设置，未知参数不做推测。",
        "quick_start": ["确认电池、存储卡和配件齐全", "先用自动模式试拍", "异常时停止使用并联系客服"],
        "setting_tips": ["运动主体提高快门速度", "光线不足时保持稳定并适当提高ISO"],
        "guide_url": None,
        "strengths": "通用拍摄",
    }
