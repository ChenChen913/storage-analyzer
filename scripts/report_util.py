# -*- coding: utf-8 -*-
"""report_util.py —— 报告模板注入相关的公共函数。"""
import json


def json_for_script(data):
    """把数据嵌进 <script> 时转义 </，避免文件名里的 </script> 提前闭合脚本。"""
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
