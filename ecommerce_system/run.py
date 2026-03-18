#!/usr/bin/env python3
"""
应用启动脚本
"""

import os
import sys

# 确保可以导入当前目录的模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web_interface import app, db


def main():
    """主函数"""
    # 获取环境变量
    env = os.environ.get('FLASK_ENV', 'development')
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    debug = os.environ.get('DEBUG', 'True').lower() == 'true'
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║          电商订单履约与数据分析系统                           ║
║                                                              ║
║  环境: {env:<15}                                          ║
║  地址: http://{host}:{port:<5}                                    ║
║  调试模式: {'开启' if debug else '关闭':<15}                        ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    # 确保数据库表存在
    with app.app_context():
        db.create_all()
        print("数据库表已初始化")
    
    # 启动应用
    app.run(
        host=host,
        port=port,
        debug=debug,
        threaded=True
    )


if __name__ == '__main__':
    main()
