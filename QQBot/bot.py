# coding: utf-8
'''
Created on 2016年5月13日

@author: zhuxj
'''
import logging
import re
import time
import datetime
from threading import Thread
from tkinter import Label
import os
from httpclient import HttpClient
from httpclient import SMART_QQ_REFER
import json
from excpetions import ServerResponseEmpty
import socket
from messages import mk_msg
from messages import (
    QMessage,
    GroupMsg,
    PrivateMsg,
    SessMsg,
)

# 创建一个logger 
logger = logging.getLogger('bot') 
logger.setLevel(logging.DEBUG) 
   
# 再创建一个handler，用于输出到控制台 
ch = logging.StreamHandler() 
ch.setLevel(logging.DEBUG) 
   
# 定义handler的输出格式 
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s') 
ch.setFormatter(formatter) 
   
# 给logger添加handler 
logger.addHandler(ch)


QR_CODE_STATUS = {
    "qr_code_expired": 65,
    "succeed": 0,
    "unexpired": 66,
    "validating": 67,
}

MESSAGE_SENT = {
    1202,
    0,
}

def find_first_result(html, regxp, error, raise_exception=False):
    founds = re.findall(regxp, html)
    tip = "Can not find given pattern [%s]in response: %s" % (regxp, error)
    if not founds:
        if raise_exception:
            raise ValueError(
               tip
            )
        logger.warning(tip)
        return ''

    return founds[0]

def date_to_millis(d):
    return int(time.mktime(d.timetuple())) * 1000

def show_qr(path):
    from tkinter import Tk
    try:
        from PIL import ImageTk, Image
    except ImportError:
        raise SystemError('缺少PIL模块, 可使用sudo pip install PIL尝试安装')

    root = Tk()
    img = ImageTk.PhotoImage(
        Image.open(path)
    )
    panel = Label(root, image=img)
    panel.pack(side="bottom", fill="both", expand="yes")
    root.mainloop()

class QRLoginFailed(UserWarning):
    pass

class CookieLoginFailed(UserWarning):
    pass

class QQBot(object):
    def __init__(self):
        self.client = HttpClient()

        # cache
        self.friend_list = {}
        self._group_sig_list = {}
        self._self_info = {}

        self.client_id = 53999199
        self.ptwebqq = ''
        self.psessionid = ''
        self.appid = 0
        self.vfwebqq = ''
        self.qrcode_path = './v.jpg'
        self.username = ''
        self.account = 0
    
    def _get_qr_login_status(
            self, qr_validation_url, appid, star_time,
            mibao_css, js_ver, sign, init_url
    ):
        redirect_url = None
        login_result = self.client.get(
            qr_validation_url.format(
                appid,
                date_to_millis(datetime.datetime.utcnow()) - star_time,
                mibao_css,
                js_ver,
                sign
            ),
            init_url
        )
        ret_code = int(find_first_result(login_result, r"\d+?", None))
        redirect_info = re.findall(r"(http.*?)\'", login_result)
        if redirect_info:
            logger.debug("redirect_info match is: %s" % redirect_info)
            redirect_url = redirect_info[0]
        return ret_code, redirect_url
    
    def check_msg(self):

        # Pooling the message
        response = self.client.post(
            'http://d1.web2.qq.com/channel/poll2',
            {
                'r': json.dumps(
                    {
                        "ptwebqq": self.ptwebqq,
                        "clientid": self.client_id,
                        "psessionid": self.psessionid,
                        "key": ""
                    }
                )
            },
            SMART_QQ_REFER
        )
        logger.debug("Pooling returns response:\n %s" % response)
        if response == "":
            return
        try:
            ret = json.loads(response)
        except ValueError:
            logger.warning("RUNTIMELOG decode poll response error.")
            logger.debug("RESPONSE {}".format(response))
            return

        ret_code = ret['retcode']

        if ret_code in (103, ):
            logger.warning(
                "Pooling received retcode: " + str(ret_code) + ": Check error. 请前往http://w.qq.com/ 手动登陆SmartQQ一次."
            )
        elif ret_code in (121,):
            logger.warning("Pooling error with retcode %s" % ret_code)
        elif ret_code == 0:
            if 'result' not in ret or len(ret['result']) == 0:
                logger.info("Pooling ends, no new message received.")
            else:
                return ret['result']
        elif ret_code == 100006:
            logger.error("Pooling request error, response is: %s" % ret)
        elif ret_code == 116:
            self.ptwebqq = ret['p']
            logger.debug("ptwebqq updated in this pooling")
        else:
            logger.warning("Pooling returns unknown retcode %s" % ret_code)
        return None
    
    def get_self_info2(self):
        """
        获取自己的信息
        get_self_info2
        {"retcode":0,"result":{"birthday":{"month":1,"year":1989,"day":30},"face":555,"phone":"","occupation":"","allow":1,"college":"","uin":2609717081,"blood":0,"constel":1,"lnick":"","vfwebqq":"68b5ff5e862ac589de4fc69ee58f3a5a9709180367cba3122a7d5194cfd43781ada3ac814868b474","homepage":"","vip_info":0,"city":"青岛","country":"中国","personal":"","shengxiao":5,"nick":"要有光","email":"","province":"山东","account":2609717081,"gender":"male","mobile":""}}
        :return:dict
        """
        if not self._self_info:
            url = "http://s.web2.qq.com/api/get_self_info2"
            response = self.client.get(url)
            rsp_json = json.loads(response)
            if rsp_json["retcode"] != 0:
                return {}
            self._self_info = rsp_json["result"]
        return self._self_info
    
    def get_online_buddies2(self):
        """
        获取在线好友列表
        get_online_buddies2
        :return:list
        """
        try:
            logger.info("RUNTIMELOG Requesting the online buddies.")
            online_buddies = json.loads(self.client.get(
                    'http://d1.web2.qq.com/channel/get_online_buddies2?vfwebqq={0}&clientid={1}&psessionid={2}&t={3}'
                        .format(
                            self.vfwebqq,
                            self.client_id,
                            self.psessionid,
                            self.client.get_timestamp()),
            ))
            logger.debug("RESPONSE get_online_buddies2 html:    " + str(online_buddies))
            if online_buddies['retcode'] != 0:
                raise TypeError('get_online_buddies2 result error')
            online_buddies = online_buddies['result']
            return online_buddies

        except:
            logger.warning("RUNTIMELOG get_online_buddies2 fail")
            return None
        
    def _login_by_cookie(self):
        logger.info("Try cookie login...")

        self.client.load_cookie()
        self.ptwebqq = self.client.get_cookie('ptwebqq')

        response = self.client.post(
            'http://d1.web2.qq.com/channel/login2',
            {
                'r': '{{"ptwebqq":"{0}","clientid":{1},"psessionid":"{2}","status":"online"}}'.format(
                    self.ptwebqq,
                    self.client_id,
                    self.psessionid
                )
            },
            SMART_QQ_REFER
        )
        try:
            ret = json.loads(response)
        except ValueError:
            logger.warning("Cookies login fail, response decode error.")
            return
        if ret['retcode'] != 0:
            raise CookieLoginFailed("Login step 1 failed with response:\n %s " % ret)

        response2 = self.client.get(
                "http://s.web2.qq.com/api/getvfwebqq?ptwebqq={0}&clientid={1}&psessionid={2}&t={3}".format(
                        self.ptwebqq,
                        self.client_id,
                        self.psessionid,
                        self.client.get_timestamp()
                ))
        ret2 = json.loads(response2)

        if ret2['retcode'] != 0:
            raise CookieLoginFailed(
                "Login step 2 failed with response:\n %s " % ret
            )

        self.psessionid = ret['result']['psessionid']
        self.account = ret['result']['uin']
        self.vfwebqq = ret2['result']['vfwebqq']

        logger.info("Login by cookie succeed. account: %s" % self.account)
        return True
    
    def _login_by_qrcode(self, no_gui):
            logger.info("RUNTIMELOG Trying to login by qrcode.")
            logger.info("RUNTIMELOG Requesting the qrcode login pages...")
            qr_validation_url = 'https://ssl.ptlogin2.qq.com/ptqrlogin?' \
                                'webqq_type=10&remember_uin=1&login2qq=1&aid={0}' \
                                '&u1=http%3A%2F%2Fw.qq.com%2Fproxy.html%3Flogin2qq%3D1%26webqq_type%3D10' \
                                '&ptredirect=0&ptlang=2052&daid=164&from_ui=1&pttype=1&dumy=' \
                                '&fp=loginerroralert&action=0-0-{1}&mibao_css={2}' \
                                '&t=undefined&g=1&js_type=0&js_ver={3}&login_sig={4}'
    
            init_url = "https://ui.ptlogin2.qq.com/cgi-bin/login?" \
                       "daid=164&target=self&style=16&mibao_css=m_webqq" \
                       "&appid=501004106&enable_qlogin=0&no_verifyimg=1" \
                       "&s_url=http%3A%2F%2Fw.qq.com%2Fproxy.html" \
                       "&f_url=loginerroralert&strong_login=1" \
                       "&login_state=10&t=20131024001"
            html = self.client.get(
                init_url,
            )
            appid = find_first_result(
                html,
                r'<input type="hidden" name="aid" value="(\d+)" />', 'Get AppId Error',
                True
            )
            sign = find_first_result(
                html,
                r'g_login_sig=encodeURIComponent\("(.*?)"\)', 'Get Login Sign Error',
            )
            js_ver = find_first_result(
                html,
                r'g_pt_version=encodeURIComponent\("(\d+)"\)',
                'Get g_pt_version Error',
                True,
            )
            mibao_css = find_first_result(
                html,
                r'g_mibao_css=encodeURIComponent\("(.+?)"\)',
                'Get g_mibao_css Error',
                True
            )
    
            star_time = date_to_millis(datetime.datetime.utcnow())
    
            error_times = 0
            ret_code = None
            login_result = None
            redirect_url = None
    
            while True:
                error_times += 1
                logger.info("Downloading QRCode file...")
                self.client.download(
                    'https://ssl.ptlogin2.qq.com/ptqrshow?appid={0}&e=0&l=L&s=8&d=72&v=4'.format(appid),
                    self.qrcode_path
                )
                if not no_gui:
                    thread = Thread(target=show_qr, args=(self.qrcode_path, ))
                    thread.setDaemon(True)
                    thread.start()
    
                while True:
                    ret_code, redirect_url = self._get_qr_login_status(
                        qr_validation_url, appid, star_time, mibao_css, js_ver,
                        sign, init_url
                    )
    
                    if ret_code in (
                            QR_CODE_STATUS['succeed'], QR_CODE_STATUS["qr_code_expired"]
                    ):
                        break
                    time.sleep(1)
    
                if ret_code == QR_CODE_STATUS['succeed'] or error_times > 10:
                    break
    
            if os.path.exists(self.qrcode_path):
                os.remove(self.qrcode_path)
    
            login_failed_tips = "QRCode validation response is:\n%s" % login_result
    
            if ret_code is not None and (ret_code != 0):
                raise QRLoginFailed(login_failed_tips)
            elif redirect_url is None:
                raise QRLoginFailed(login_failed_tips)
            else:
                html = self.client.get(redirect_url)
                logger.debug("QR Login redirect_url response: %s" % html)
                return True
    
    def login(self, no_gui=False):
        try:
            self._login_by_cookie()
        except CookieLoginFailed:
            logger.info("Cookie login failed.")
            while True:
                if self._login_by_qrcode(no_gui):
                    if self._login_by_cookie():
                        break
                time.sleep(4)
        user_info = self.get_self_info2()
        self.get_online_buddies2()
        try:
            self.username = user_info['nick']
            logger.info(
                "User information got: user name is [%s]" % self.username
            )
        except KeyError:
            logger.exception(
                "User info access failed, check your login and response:\n%s"
                % user_info
            )
            exit(1)
        logger.info("RUNTIMELOG QQ：{0} login successfully, Username：{1}".format(self.account, self.username))
        self._self_info = user_info
    
    def getTulin(self, info):
        logger.info("Try Tulin...")

        self.client.load_cookie()
        response = self.client.post(
            'http://www.tuling123.com/openapi/api',
            {
                'key': '46dec4507ea59630889dce242767ca9b',
                'info':info
            }
        )
        print(response)
        try:
            ret = json.loads(response)
        except ValueError:
            logger.warning("Tulin connect fail, response decode error.")
            return
        logger.info("Tulin connect succeed. account: %s" % ret)
        return ret['text']

    # 发送群消息
    def send_qun_msg(self, reply_content, guin, msg_id, fail_times=0):
        fix_content = str(reply_content.replace("\\", "\\\\\\\\").replace("\n", "\\\\n").replace("\t", "\\\\t"))
        rsp = ""
        try:
            logger.info("Starting send group message: %s" % reply_content)
            req_url = "http://d1.web2.qq.com/channel/send_qun_msg2"
            data = (
                ('r',
                 '{{"group_uin":{0}, "face":564,"content":"[\\"{4}\\",[\\"font\\",{{\\"name\\":\\"Arial\\",\\"size\\":\\"10\\",\\"style\\":[0,0,0],\\"color\\":\\"000000\\"}}]]","clientid":{1},"msg_id":{2},"psessionid":"{3}"}}'.format(
                         guin, self.client_id, msg_id, self.psessionid, fix_content)),
                ('clientid', self.client_id),
                ('psessionid', self.psessionid)
            )
            rsp = self.client.post(req_url, data, SMART_QQ_REFER)
            rsp_json = json.loads(rsp)
            if 'retcode' in rsp_json and rsp_json['retcode'] not in MESSAGE_SENT:
                raise ValueError("RUNTIMELOG reply group chat error" + str(rsp_json['retcode']))
            logger.info("RUNTIMELOG send_qun_msg: Reply '{}' successfully.".format(reply_content))
            logger.debug("RESPONSE send_qun_msg: Reply response: " + str(rsp))
            return rsp_json
        except:
            logger.warning("RUNTIMELOG send_qun_msg fail")
            if fail_times < 5:
                logger.warning("RUNTIMELOG send_qun_msg: Response Error.Wait for 2s and Retrying." + str(fail_times))
                logger.debug("RESPONSE send_qun_msg rsp:" + str(rsp))
                time.sleep(2)
                self.send_qun_msg(guin, reply_content, msg_id, fail_times + 1)
            else:
                logger.warning("RUNTIMELOG send_qun_msg: Response Error over 5 times.Exit.reply content:" + str(reply_content))
                return False
    
    # 发送私密消息
    def send_buddy_msg(self, reply_content, tuin, msg_id, fail_times=0):
        fix_content = str(reply_content.replace("\\", "\\\\\\\\").replace("\n", "\\\\n").replace("\t", "\\\\t"))
        rsp = ""
        try:
            req_url = "http://d1.web2.qq.com/channel/send_buddy_msg2"
            data = (
                ('r',
                 '{{"to":{0}, "face":594, "content":"[\\"{4}\\", [\\"font\\", {{\\"name\\":\\"Arial\\", \\"size\\":\\"10\\", \\"style\\":[0, 0, 0], \\"color\\":\\"000000\\"}}]]", "clientid":{1}, "msg_id":{2}, "psessionid":"{3}"}}'.format(
                         tuin, self.client_id, msg_id, self.psessionid, fix_content)),
                ('clientid', self.client_id),
                ('psessionid', self.psessionid)
            )
            rsp = self.client.post(req_url, data, SMART_QQ_REFER)
            rsp_json = json.loads(rsp)
            if 'errCode' in rsp_json and rsp_json['errCode'] != 0:
                raise ValueError("reply pmchat error" + str(rsp_json['retcode']))
            logger.info("RUNTIMELOG Reply successfully.")
            logger.debug("RESPONSE Reply response: " + str(rsp))
            return rsp_json
        except:
            if fail_times < 5:
                logger.warning("RUNTIMELOG Response Error.Wait for 2s and Retrying." + str(fail_times))
                logger.debug("RESPONSE " + str(rsp))
                time.sleep(2)
                self.send_buddy_msg(tuin, reply_content, msg_id, fail_times + 1)
            else:
                logger.warning("RUNTIMELOG Response Error over 5 times.Exit.reply content:" + str(reply_content))
                return False
    
    def reply_msg(self, msg, reply_content=None, return_function=False):
        """
        :type msg: QMessage类, 例如 GroupMsg, PrivateMsg, SessMsg
        :type reply_content: string, 回复的内容.
        :return: 服务器的响应内容. 如果 return_function 为 True, 则返回的是一个仅有 reply_content 参数的便捷回复函数.
        """
        import functools
        assert isinstance(msg, QMessage)
        if isinstance(msg, GroupMsg):
            if return_function:
                return functools.partial(self.send_qun_msg, guin=msg.group_code, msg_id=msg.msg_id+1)
            return self.send_qun_msg(guin=msg.group_code, reply_content=reply_content, msg_id=msg.msg_id+1)
        if isinstance(msg, PrivateMsg):
            if return_function:
                return functools.partial(self.send_buddy_msg, tuin=msg.from_uin, msg_id=msg.msg_id+1)
            return self.send_buddy_msg(tuin=msg.from_uin, reply_content=reply_content, msg_id=msg.msg_id+1)
        if isinstance(msg, SessMsg):
            pass
bot = QQBot()
bot.login(False)
while True:
    try:
        msg_list = bot.check_msg()
        if msg_list is not None:
            for msg in msg_list:
                message=mk_msg(msg)
                if '@Robot' in message.content:
                    bot.reply_msg(message, bot.getTulin(message.content.replace('@Robot', '')))
                    break;
                if 'Robot' in message.content:
                    bot.reply_msg(message, bot.getTulin(message.content.replace('Robot', '')))
    except ServerResponseEmpty:
        continue
    except (socket.timeout, IOError):
        logger.warning("Message pooling timeout, retrying...")
    except Exception:
        logger.exception("Exception occurs when checking msg.")