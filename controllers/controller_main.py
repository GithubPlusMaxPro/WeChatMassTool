# -*- coding: utf-8 -*-
# Name:         controller_main.py
# Author:       小菜
# Date:         2024/04/01 00:00
# Description:
from copy import deepcopy
import requests
import time

from PySide6.QtCore import (QObject, QMutexLocker, QMutex, QWaitCondition, 
                           Slot, QThread, Signal, Qt)
from PySide6.QtWidgets import (QFileDialog, QMessageBox)

from config import (Animate, WeChat, TUTORIAL_LINK)
from models import ModelMain
from utils import (
    read_file, write_file, write_config, get_file_sha256, get_temp_file_path, path_exists, delete_file, join_path,
    open_webpage
)
from views import ViewMain


class ControllerMain(QObject):
    messageProcessed = Signal()  # 添加新的信号用于通知消息处理完成

    def __init__(self, animate_on_startup=True, parent=None):
        super().__init__(parent)
        self.view = ViewMain(animate_on_startup)
        self.model = ModelMain()

        # 互斥锁 和 条件等待
        self.paused = False
        self.mutex = QMutex()
        self.pause_condition = QWaitCondition()
        #
        self.setup_connections()
        self.name_list = list()
        self.name_list_file = str()
        self.sha256_cache_file = str()
        self.init_animate_radio_btn(flag=animate_on_startup)
        self.auto_send_thread = None
        self.messageProcessed.connect(self.continue_auto_send)  # 连接新的槽函数
        self.total_messages = 0
        self.current_message_index = 0
        self.messages_cache = []

    def setup_connections(self):
        # 发送消息
        self.view.btn_send_msg.clicked.connect(self.on_send_clicked)
        self.view.btn_pause_send.clicked.connect(self.toggle_send_status)

        # 自动发送开始
        self.view.btn_send_msg_2.clicked.connect(self.on_send_clicked_auto)
        # 清空控件
        self.view.btn_clear_msg.clicked.connect(self.view.clear_msg_text_edit)
        self.view.btn_clear_name.clicked.connect(self.clear_name_actions)
        self.view.btn_clear_file.clicked.connect(self.view.clear_file_list_widget)
        self.view.btn_clear_all.clicked.connect(self.clear_all_actions)
        # 添加文件
        self.view.btn_add_file.clicked.connect(self.import_send_file_list)
        self.view.filesDropped.connect(self.import_send_file_list)
        self.view.btn_import_name_list.clicked.connect(self.import_name_list)
        self.view.btn_export_name_list.clicked.connect(self.export_tag_name_list)
        self.view.btn_export_chat_group_name_list.clicked.connect(self.export_chat_group_name_list)
        # 导出运行结果
        self.view.btn_export_result.clicked.connect(self.export_exec_result)
        # 添加 文件 QListWidget 控件右键菜单
        self.view.add_list_widget_menu()
        # 进度条, 导出按钮, 显示信息栏, 缓存进度, 删除缓存进度,的 Signal
        self.view.updatedProgressSignal.connect(self.view.update_progress)
        self.model.exportNameListSignal.connect(self.show_export_msg_box)
        self.model.exportChatGroupNameListSignal.connect(self.show_export_msg_box)
        self.model.showInfoBarSignal.connect(self.show_infobar)
        self.model.cacheProgressSignal.connect(self.cache_progress)
        self.model.deleteCacheProgressSignal.connect(self.delete_cache_progress)
        # 开启和关闭动画启动按钮
        self.view.radio_btn_animate_true.clicked.connect(self.set_animate_startup_status)
        self.view.radio_btn_animate_false.clicked.connect(self.set_animate_startup_status)
        # 双击打开教程
        self.view.textEdit.mouseDoubleClickEvent = lambda x: open_webpage(TUTORIAL_LINK)

    def get_gui_info(self):
        """获取当前面板填写的信息"""
        single_text = self.view.single_line_msg_text_edit.toPlainText()
        multi_text = self.view.multi_line_msg_text_edit.toPlainText()
        files = [self.view.file_list_widget.item(row).text() for row in range(self.view.file_list_widget.count())]
        names = self.view.name_text_edit.toPlainText()
        add_remark_name = True if self.view.rb_add_remark.isChecked() else False
        at_everyone = True if self.view.rb_at_everyone.isChecked() else False
        text_interval = float(self.view.cb_text_interval.currentText())
        file_interval = float(self.view.cb_file_interval.currentText())
        send_shortcut = '{Enter}' if self.view.radio_btn_enter.isChecked() else '{Ctrl}{Enter}'
        return {
            'single_text': single_text,
            'multi_text': multi_text,
            'file_paths': files,
            'names': names,
            'name_list': deepcopy(self.name_list),
            'text_name_list_count': len(self.name_list),
            'add_remark_name': add_remark_name,
            'at_everyone': at_everyone,
            'text_interval': text_interval,
            'file_interval': file_interval,
            'send_shortcut': send_shortcut
        }
    
    
    def get_gui_info_auto(self, item):
        """获取当前面板填写的信息"""
        single_text = ''
        multi_text = item['message']
        files = []
        names = item['wechat_group']
        add_remark_name = False
        at_everyone = False
        text_interval = 0.1  # 将文本发送间隔改为0.1秒
        file_interval = 0.1  # 将文件发送间隔改为0.1秒
        send_shortcut = '{Enter}' if self.view.radio_btn_enter.isChecked() else '{Ctrl}{Enter}'
        return {
            'single_text': single_text,
            'multi_text': multi_text,
            'file_paths': files,
            'names': names,
            'name_list': [],
            'text_name_list_count': 0,
            'add_remark_name': add_remark_name,
            'at_everyone': at_everyone,
            'text_interval': text_interval,
            'file_interval': file_interval,
            'send_shortcut': send_shortcut
        }

    # noinspection PyUnresolvedReferences
    def import_name_list(self) -> None:
        """添加昵称清单"""
        if name_list_file := QFileDialog.getOpenFileName(self.view, '选择文件', '', "Text Files (*.txt)")[0]:
            self.view.set_text_in_widget('import_name_list_line_edit', name_list_file)
            self.name_list = read_file(file=name_list_file)
            self.name_list_file = name_list_file
            self.view.show_message_box('导入成功!', QMessageBox.Information)
        else:
            self.name_list = list()
            self.view.set_text_in_widget('import_name_list_line_edit', '')
            self.view.show_message_box('导入失败!', QMessageBox.Critical, duration=3000)
        # 简单更新progress的数量
        self.update_task_progress()

    def import_send_file_list(self, new_files):
        """导入发送名单"""
        if not new_files:
            new_files = set(QFileDialog.getOpenFileNames(self.view, '选择文件', "All Files (*);;*")[0])
        curr_files = {self.view.file_list_widget.item(row).text() for row in range(self.view.file_list_widget.count())}
        # 计算尚未添加到列表的新文件
        if files_to_add := (new_files - curr_files):
            self.view.file_list_widget.addItems(files_to_add)

    def export_tag_name_list(self):
        """导出标签好友名单"""
        if not self.view.export_tag_name_list_line_edit.text():
            self.view.show_message_box('无标签名称!', QMessageBox.Critical, duration=1500)
            return
        if file_path := QFileDialog.getSaveFileName(self.view, "Create File", "untitled.txt", "Text Files (*.txt)")[0]:
            if file_path.endswith('.txt'):
                # 保存文件
                self.model.export_name_list(self.view.export_tag_name_list_line_edit.text(), file_path)
        else:
            self.name_list = list()
            self.view.set_text_in_widget('export_tag_name_list_line_edit', '')
            self.view.show_message_box('导入失败!', QMessageBox.Critical, duration=3000)
            return

    def export_chat_group_name_list(self):
        """导出群聊名称"""
        if file_path := QFileDialog.getSaveFileName(self.view, "Create File", "untitled.txt", "Text Files (*.txt)")[0]:
            if file_path.endswith('.txt'):
                # 保存文件
                # self.model.export_name_list(self.view.export_tag_name_list_line_edit.text(), file_path)
                self.model.export_chat_group_name_list(file_path)

    def on_send_clicked(self):
        """点击发送按钮触发的事件"""
        data = self.get_gui_info()
        print(data)
        print('11111测试嘤嘤嘤')
        if cache_index := self.get_name_list_file_cache_index():
            data['cache_index'] = cache_index
        print(data)
        self.model.send_wechat_message(
            data,
            check_pause=self.check_pause,
            updatedProgressSignal=self.view.updatedProgressSignal,
        )


    def on_send_clicked_auto(self):
        """点击自动发送按钮触发的事件"""
        if self.auto_send_thread and self.auto_send_thread.isRunning():
            self.auto_send_thread.stop()
            self.view.btn_send_msg_2.setText("开始自动发送")
            return
            
        self.auto_send_thread = AutoSendThread(self)
        self.auto_send_thread.dataReceived.connect(self.handle_auto_send_data)
        self.auto_send_thread.error.connect(self.handle_auto_send_error)
        self.auto_send_thread.start()
        self.view.btn_send_msg_2.setText("停止自动发送")
        
    def handle_auto_send_data(self, data):
        """处理收到的数据"""
        try:
            # 记录总消息数和当前处理的索引
            self.total_messages = len(data)
            self.current_message_index = 0
            self.messages_cache = data  # 保存消息缓存
            
            # 处理第一条消息
            self.process_next_message(data)
            
        except Exception as e:
            print(f"处理消息时出错: {str(e)}")
            self.messageProcessed.emit()  # 出错时继续下一轮

    def process_next_message(self, messages):
        """处理下一条消息"""
        try:
            if self.current_message_index < self.total_messages:
                message = messages[self.current_message_index]
                formatted_data = self.get_gui_info_auto(message)
                
                # 连接一次性槽函数来处理消息发送完成
                self.model.showInfoBarSignal.connect(self.on_message_sent, type=Qt.SingleShotConnection)
                
                self.model.send_wechat_message_auto(
                    formatted_data,
                    check_pause=self.check_pause,
                    updatedProgressSignal=self.view.updatedProgressSignal,
                )
            else:
                # 所有消息都处理完成，发出信号继续下一轮
                self.messageProcessed.emit()
                
        except Exception as e:
            print(f"处理消息时出错: {str(e)}")
            self.messageProcessed.emit()

    def on_message_sent(self, success, message):
        """消息发送完成的回调"""
        # 断开信号连接
        try:
            self.model.showInfoBarSignal.disconnect(self.on_message_sent)
        except:
            pass
        
        if success:
            print(f"消息 {self.current_message_index + 1}/{self.total_messages} 发送成功")
        else:
            print(f"消息 {self.current_message_index + 1}/{self.total_messages} 发送失败: {message}")
        
        # 处理下一条消息
        self.current_message_index += 1
        self.process_next_message(self.messages_cache)

    def handle_auto_send_error(self, error_msg):
        """处理错误信息"""
        print(f'请求发生错误: {error_msg}')
        self.view.show_message_box('数据格式错误!', QMessageBox.Critical, duration=3000)

    def check_pause(self):
        """检查暂停"""
        if self.paused:
            with QMutexLocker(self.mutex):
                self.pause_condition.wait(self.mutex)

    def toggle_send_status(self):
        """切换暂停状态"""
        self.paused = not self.paused
        with QMutexLocker(self.mutex):
            if not self.paused:
                self.pause_condition.wakeAll()
        # 切换按钮文本 和 图标
        current_text = self.view.btn_pause_send.text()
        self.view.btn_pause_send.setText('暂停发送' if current_text == '继续发送' else '继续发送')
        self.view.pause_and_continue_send()

    # noinspection PyUnresolvedReferences
    def export_exec_result(self):
        """导出运行结果"""
        if file_path := QFileDialog.getSaveFileName(self.view, "Create File", "运行结果.csv", "CSV Files (*.csv)")[0]:
            res = self.model.record.export_exec_result_to_csv(file_path)
            icon = QMessageBox.Information if res.get('status') else QMessageBox.Critical
            self.view.show_message_box(res.get('tip'), icon, duration=3000)
        else:
            self.view.show_message_box('导出失败!', QMessageBox.Critical, duration=3000)

    def clear_name_actions(self):
        """清空 名字清单 控件"""
        self.view.clear_name_text_edit()
        self.name_list = list()

    def clear_all_actions(self):
        """清空 全部 控件"""
        self.view.clear_all_text_edit()
        self.name_list = list()

    def init_animate_radio_btn(self, flag):
        """初始化动画配置单选按钮"""
        if flag:
            self.view.radio_btn_animate_true.click()
        else:
            self.view.radio_btn_animate_false.click()

    def set_animate_startup_status(self):
        """设置动画配置单选按钮状态"""
        if self.view.radio_btn_animate_true.isChecked():
            write_config(WeChat.APP_NAME, Animate.SECTION, Animate.OPTION, value=str(True))
        else:
            write_config(WeChat.APP_NAME, Animate.SECTION, Animate.OPTION, value=str(False))

    def get_name_list_file_cache_index(self):
        """
        获取缓存进度的索引

        Returns:
            int: 缓存进度的索引
        """
        if self.name_list_file:
            self.sha256_cache_file = get_temp_file_path(
                join_path(WeChat.APP_NAME, get_file_sha256(self.name_list_file) + '.tmp')
            )
            # print(self.sha256_cache_file)
            if path_exists(self.sha256_cache_file):
                return read_file(self.sha256_cache_file)[0]
        return int(0)

    def update_task_progress(self):
        """初始化更新progress的数量"""
        count = len(self.name_list) + len(_.split('\n') if (_ := self.view.name_text_edit.toPlainText()) else list())
        self.view.updatedProgressSignal.emit(0, count)

    @Slot(bool, str)
    def show_export_msg_box(self, status, tip):
        """展示导出消息的弹窗"""
        icon = QMessageBox.Information if status else QMessageBox.Critical
        self.view.show_message_box(message=tip, icon=icon)

    @Slot(bool, str)
    def show_infobar(self, status, tip):
        icon_type = 'success' if status else 'fail'
        self.view.add_infobar(tip, icon_type)

    @Slot(str)
    def cache_progress(self, index):
        write_file(self.sha256_cache_file, data=[index])

    @Slot(bool)
    def delete_cache_progress(self, item):
        delete_file(self.sha256_cache_file)

    def continue_auto_send(self):
        """继续自动发送的槽函数"""
        if self.auto_send_thread and self.auto_send_thread.isRunning():
            self.auto_send_thread.resume()


class AutoSendThread(QThread):
    dataReceived = Signal(list)
    error = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop = False
        self._interval = 0.1
        self._paused = False  # 添加暂停标志
        self._pause_mutex = QMutex()
        self._pause_condition = QWaitCondition()
        
    def run(self):
        url = "https://sf-erp.xtli.cc/sys/worktool/createMockData"
        
        while not self._stop:
            try:
                response = requests.get(url)
                if response.status_code == 200:
                    response_data = response.json()
                    if response_data.get('status') == 200:
                        messages = response_data.get('data', [])
                        print(messages)
                        if messages:
                            self.dataReceived.emit(messages)
                            # 发送数据后暂停等待处理完成
                            self._pause()
                    else:
                        self.error.emit(f'数据格式错误: {response_data}')
                
                time.sleep(self._interval)
                
            except Exception as e:
                self.error.emit(str(e))
                time.sleep(1)
    
    def _pause(self):
        """暂停线程执行"""
        with QMutexLocker(self._pause_mutex):
            self._paused = True
            while self._paused and not self._stop:
                self._pause_condition.wait(self._pause_mutex)
    
    def resume(self):
        """恢复线程执行"""
        with QMutexLocker(self._pause_mutex):
            self._paused = False
            self._pause_condition.wakeAll()
                
    def stop(self):
        """停止线程"""
        self._stop = True
        self.resume()  # 确保线程能够退出
