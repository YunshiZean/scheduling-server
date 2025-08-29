# coding=utf-8
"""
文件名： scheduling_server.py
简介： 小车调度服务器
版本： 2.0
更新： 将控制改成原先的回车型，同时修复了连接问题
最后更新时间： 2025.8.7
创建时间： 2025.8.29
"""

import socket
import threading
import time
import json
import os
from typing import Dict
from enum import Enum, auto
from colorama import init, Fore
import inspect
import keyboard

# 日志输出到三个文件
os.makedirs("logs", exist_ok=True)
log_up = open("logs/up.log", "w")  # 记录上行消息信息
log_down = open("logs/down.log", "w")  # 记录下行消息信息

def log_line():
    frame = inspect.currentframe().f_back
    print(f"行号: {frame.f_lineno}, 文件: {frame.f_code.co_filename}, 函数: {frame.f_code.co_name}")

def log_up_line(msg):
    print(msg, file=log_up, flush=True)

def log_down_line(msg):
    print(msg, file=log_down, flush=True)


import msvcrt

def clear_input_buffer():
    while msvcrt.kbhit():  # 检查键盘缓冲区是否有数据
        msvcrt.getch()     # 逐个读走丢弃


init(autoreset=True)

def print_error(msg):
    print(os.path.basename(__file__) + Fore.RED + f": [error:{time.time()}] " + str(msg) + "\n")
    # log_line()

def print_success(msg):
    print(os.path.basename(__file__) + Fore.GREEN + ": [success:{time.time()}] " + str(msg) + "\n")

def print_warn(msg):
    print(os.path.basename(__file__) + Fore.YELLOW + ": [warn:{time.time()}] " + str(msg))
    # log_line()

def print_info(msg):
    print(os.path.basename(__file__) + Fore.WHITE + f": [info:{time.time()}] " + str(msg) + "\n")

def get_local_ip():
    try:
        # s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # s.connect(("8.8.8.8", 80))
        # ip = s.getsockname()[0]
        # s.close()
        ip = "192.168.203.8"
        return ip
    except Exception:
        return "127.0.0.1"


class ServerBroadcaster:
    def __init__(self, port: int, broadcast_port: int = 9999):
        self.port = port
        self.broadcast_port = broadcast_port
        self.local_ip = get_local_ip()
        self.running = False
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._broadcast_loop, daemon=True)
        self.thread.start()
        print(f"[INFO] 启动广播线程，每秒发送本机地址 {self.local_ip}:{self.port}")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()
        print("[INFO] 广播线程已停止")

    def _broadcast_loop(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        message = f"SERVER:{self.local_ip}:{self.port}".encode('utf-8')
        while self.running:
            try:
                s.sendto(message, ('255.255.255.255', self.broadcast_port))
                time.sleep(1)
            except Exception as e:
                print(f"[ERROR] 广播失败: {e}")
                break
        s.close()




class CarState(Enum):
    """
    用来描述小车可用状态的枚举
    """
    IDLE = auto()
    CRUISE = auto()
    TASK = auto()
    CARRYING = auto()
    POWER = auto()
    UNKNOWN = auto()

class CarBattery(Enum):
    """
    电池电量枚举
    """
    FULL = auto() #满电
    ENOUGH = auto() #高于一半
    ATTENTION = auto() #低于一半
    LOW = auto() #过低
    UNKNOW = auto() #不知道

class CarInfo:
    def __init__(self):
        self.current_point = None
        self.current_state = self.RobotState.UNKNOWN
        self.last_state = self.RobotState.UNKNOWN
        self.current_path = ""
        self.cruise_index = 0
        self.task_queue = []
        self.power_level: CarBattery = CarBattery.UNKNOW

    class RobotState(Enum):
        IDLE = auto()
        CRUISE = auto()
        TASK = auto()
        CARRYING = auto()
        INIT = auto()
        POWER = auto()
        UNKNOWN = auto()

    def to_json(self):
        data = {
            "current_point": self.current_point,
            "current_state": self.current_state.name,
            "last_state": self.last_state.name,
            "current_path": self.current_path,
            "cruise_index": self.cruise_index,
            "task_queue": self.task_queue
        }
        return json.dumps(data)

    def from_json(self, json_data):
        data = json.loads(json_data)
        self.current_point = data.get("current_point")
        self.current_state = self.RobotState[data.get("current_state")]
        self.last_state = self.RobotState[data.get("last_state")]
        self.current_path = data.get("current_path")
        self.cruise_index = data.get("cruise_index")
        self.task_queue = data.get("task_queue")
        self.power_level = CarBattery[data.get("power_level")]
        if self.power_level is None: #刷新信息的时候电压值是空的，默认为未知
            self.power_level = CarBattery.UNKNOW

class Car:
    def __init__(self, ip: str):
        self.car_info = CarInfo()
        self.ip = ip
        self.last_heartbeat = time.time()
        self.state:CarState = CarState.IDLE
        self.up_socket = None
        self.down_socket = None

    def update(self, message: str):
        self.last_heartbeat = time.time()
        log_up_line(f"[Car更新] 来自 {self.ip} 的消息：{message},时间为：{time.time()}")

    def send(self, msg: str):
        if self.down_socket:
            try:
                self.down_socket.sendall(msg.encode("utf-8"))
                log_down_line(f"[下发] 向 {self.ip} 发送：{msg}")
            except Exception as e:
                log_down_line(f"[下发失败] {self.ip}：{e}")

    def grong_vjug(self, other_car:"Car"):
        """
        夺舍函数，将该设备的全部重要信息发送给另一台车，达到夺舍的目的
        :param other_car: 要夺舍的对象
        :return:
        """
        selfinfo = self.car_info.to_json()
        other_car.send("/info "+selfinfo)
        other_car.car_info.from_json(selfinfo) #刷新信息,避免重复发送



class CarServer:
    def __init__(self, port_up: int):

        self.car1_ip = "192.168.203.18"
        self.car2_ip = "192.168.203.37"
        self.car3_ip = "192.168.203.47"

        self.port_up = port_up
        self.port_down = port_up + 1
        self.port_alive = port_up + 2
        self.local_ip = get_local_ip()
        self.running = False
        self.car_map: Dict[str, Car] = {}

    def start(self):
        self.running = True
        threading.Thread(target=self.tcp_alive_loop, daemon=True).start()
        threading.Thread(target=self.tcp_up_loop, daemon=True).start()
        threading.Thread(target=self.tcp_down_loop, daemon=True).start()
        print_info(f"[服务端] 上行 {self.local_ip}:{self.port_up}，下行 {self.port_down}，等待小车连接...")
        threading.Thread(target=self.monitor_loop, daemon=True).start()

    def stop(self):
        self.running = False
        print_info("[服务端] 停止运行")

    def tcp_alive_loop(self):
        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp_socket.bind((self.local_ip, self.port_alive))
        tcp_socket.listen(5)
        print_success("[TCP验证] 启动成功")
        while self.running:
            try:
                client_sock, addr = tcp_socket.accept()
                print_success(f"[新连接_alive] 小车连接自 {addr}")
                threading.Thread(target=self.handle_alive, args=(client_sock, addr), daemon=True).start()
            except Exception as e:
                print_error(f"[TCP验证错误] {e}")
                time.sleep(1)
        tcp_socket.close()

    def tcp_up_loop(self):
        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp_socket.bind((self.local_ip, self.port_up))
        tcp_socket.listen(5)
        print_success("[TCP上行] 启动成功")
        while self.running:
            try:
                client_sock, addr = tcp_socket.accept()
                print_success(f"[新连接_UP] 小车连接自 {addr}")
                threading.Thread(target=self.handle_up, args=(client_sock, addr), daemon=True).start()
            except Exception as e:
                print_error(f"[TCP上行错误] {e}")
                time.sleep(1)
        tcp_socket.close()

    def tcp_down_loop(self):
        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # tcp_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        tcp_socket.bind((self.local_ip, self.port_down))
        tcp_socket.listen(5)
        print_success("[TCP下行] 启动成功")
        while self.running:
            try:
                client_sock, addr = tcp_socket.accept()
                print_success(f"[新连接_DOWN] 小车连接自 {addr}")
                threading.Thread(target=self.handle_down, args=(client_sock, addr), daemon=True).start()
            except Exception as e:
                print_error(f"[TCP下行错误] {e}")
                time.sleep(1)
        tcp_socket.close()




    def handle_up_message(self, message: str):
        if " " in message:
            return message.split(" ", 1)
        return message, None




    def handle_alive(self, sock: socket.socket, addr):
        ip, _ = addr
        if ip not in self.car_map:
            self.car_map[ip] = Car(ip)
        car = self.car_map[ip]
        with sock:
            try:
                while self.running:
                    alive = sock.recv(6) #由于只接收很短的验证信息，这里只接受少量数据
                    if not alive:
                        log_up_line(f"[断开] 小车 {car.ip} 验证断开")
                        break
                    car.update(alive.decode("utf-8"))
            except Exception as e:
                log_up_line(f"[验证错误] {car.ip}: {e}")

    def handle_up(self, sock: socket.socket, addr):
        ip, _ = addr
        if ip not in self.car_map:
            self.car_map[ip] = Car(ip)
        car = self.car_map[ip]
        car.up_socket = sock

        message = ""
        with sock:
            try:
                while self.running:
                    data = sock.recv(1024)
                    if not data:
                        log_up_line(f"[断开] 小车 {car.ip} 上行断开")
                        break
                    car.update(data.decode("utf-8")) #顺便刷新心跳
                    # message += data.decode('utf-8')
                    # while '\n' in message:
                    #     _message, message = message.split('\n', 1)
                    #     cmd, data = self.handle_up_message(_message)
                    #     if cmd == "/info":
                    #         car.car_info.from_json(data)
                    #         #可用信息的转换
                    #         if car.car_info.current_state == CarInfo.RobotState.UNKNOWN:
                    #             car.state = CarState.UNKNOWN
                    #         elif car.car_info.current_state == CarInfo.RobotState.IDLE or car.car_info.current_state == CarInfo.RobotState.INIT:
                    #             car.state = CarState.IDLE
                    #         elif car.car_info.current_state == CarInfo.RobotState.CARRYING:
                    #             car.state = CarState.CARRYING
                    #         elif car.car_info.current_state == CarInfo.RobotState.CRUISE:
                    #             car.state = CarState.CRUISE
                    #         elif car.car_info.current_state == CarInfo.RobotState.TASK:
                    #             car.state = CarState.TASK
                    #         elif car.car_info.current_state == CarInfo.RobotState.POWER: #如果状态是在充电
                    #             if car.state != CarState.IDLE: #如果状态不是空闲
                    #                 car.state = CarState.POWER #状态改为充电
                    #                 if car.car_info.power_level == CarBattery.FULL: #如果电量是满
                    #                     if car.state != CarState.IDLE: #如果状态不是空闲
                    #                         car.state = CarState.IDLE #状态改为空闲
                    #         if car.state != CarState.POWER:
                    #             if car.car_info.power_level == CarBattery.ATTENTION: #如果电量低于一半，就看看有没有空闲的车辆
                    #                 for other_car in self.car_map.values():
                    #                     if other_car != car:
                    #                         if other_car.state == CarState.IDLE:
                    #                             car.grong_vjug(other_car) #那就直接夺舍过去，本体去充电
                    #                             car.send("/go_power") #告诉小车去充电
                    #                             car.state = CarState.POWER
                    #                             break
                        # elif cmd == "/power_low":
                        #     #只有当设备没有在充电的时候，才去寻找充电车辆
                        #     if car.state != CarState.POWER:
                        #         if car.car_info.power_level != CarBattery.LOW:
                        #             car.car_info.power_level = CarBattery.LOW
                        #             print_warn(f"[电量低] {car.ip}")
                                #找可用车辆，懒得搞算法了，直接循环三次吧，又不是编译型语言，文件打点就大点
                                #管它黑代码白代码，能实现功能就是好代码
                                # i = True
                                # for other_car in self.car_map.values():
                                #     if other_car != car:
                                #         if other_car.state == CarState.IDLE:
                                #             car.grong_vjug(other_car)
                                #             car.send("/go_power")  # 告诉小车去充电
                                #             i = False
                                #             break
                                # if i:
                                #     for other_car in self.car_map.values():
                                #         if other_car != car:
                                #             if other_car.car_info.power_level == CarBattery.ENOUGH or other_car.car_info.power_level == CarBattery.FULL:
                                #                 car.grong_vjug(other_car)
                                #                 car.send("/go_power")  # 告诉小车去充电
                                #                 i = False
                                #                 break
                                # if i:
                                #     for other_car in self.car_map.values():
                                #         if other_car != car:
                                #             if other_car.state == CarState.CRUISE:
                                #                 car.grong_vjug(other_car)
                                #                 car.send("/go_power")  # 告诉小车去充电
                                #                 i = False
                                #                 break
                                # if i:
                                #     #如果搞完这些尝试，还是没有可用车辆，那没得办法了，到下一站后去充电吧，游客什么的 life find way out
                                #     car.grong_vjug(self.car_map[self.car2_ip])
                                #     car.send("/go_power")
                                #     i = False
                                #     break
            except Exception as e:
                log_up_line(f"[接收错误] {car.ip}: {e}")

    def handle_down(self, sock: socket.socket, addr):
        ip, _ = addr
        if ip not in self.car_map:
            self.car_map[ip] = Car(ip)
        car = self.car_map[ip]
        car.down_socket = sock
        with sock:
            # try:
            while self.running:
                pass
            #         msg = input("请输入要下发的消息：")
            #         car.send(msg)
            # except Exception as e:
            #     log_down_line(f"[发送失败] {car.ip}: {e}")





    def monitor_loop(self):
        while self.running:
            for ip, car in list(self.car_map.items()):
                #print_warn(f"{car.ip}:{time.time() - car.last_heartbeat}")
                if time.time() - car.last_heartbeat > 15:
                    if car.state != CarState.UNKNOWN:
                        car.state = CarState.UNKNOWN
                        print_error(f"[超时] 小车 {car.ip} 超过15秒未响应，可能掉线，状态已切换")
            time.sleep(2)




def handle_cmd_select(_car_id:str,_cmd:str):
    if _cmd is None or _cmd == "/":
        print_error("格式错误")
        return
    if _car_id == "1":
        try:
            server.car_map[server.car1_ip].send(_cmd)
        except Exception as e:
            print_error(f"1发送失败：{e}")
    elif _car_id == "2":
        try:
            server.car_map[server.car2_ip].send(_cmd)
        except Exception as e:
            print_error(f"2发送失败：{e}")
    elif _car_id == "3":
        try:
            server.car_map[server.car3_ip].send(_cmd)
        except Exception as e:
            print_error(f"3发送失败：{e}")
    elif _car_id == "-1":
        try:
            server.car_map[server.car1_ip].send(_cmd)
        except Exception as e:
            print_error(f"1发送失败：{e}")
        try:
            server.car_map[server.car2_ip].send(_cmd)
        except Exception as e:
            print_error(f"2发送失败：{e}")
        try:
            server.car_map[server.car3_ip].send(_cmd)
        except Exception as e:
            print_error(f"3发送失败：{e}")





if __name__ == "__main__":
    net_config_path = os.path.join(os.path.join(os.path.dirname(__file__), "..", "config"), "net_config.json")
    with open(net_config_path, "r") as f:
        net_config = json.load(f)
        SERVER_PORT = int(net_config["SERVER_PORT"])

    broadcaster = ServerBroadcaster(port=SERVER_PORT)
    broadcaster.start()

    server = CarServer(SERVER_PORT)
    server.start()

    time.sleep(5)
    try:
        car_id = ""
        cmd = ""
        while True:
            Is_cmd = False
            input_cmd = input("请输入指令：")
            try:
                car_id, cmd = input_cmd.split(" ",1)
                Is_cmd = True
            except:
                Is_cmd = False
            print(input_cmd)
            if Is_cmd: #如果输入了小车id
                handle_cmd_select(car_id, cmd) #就去处理
            else: #否则则是特殊控制指令，统一处理
                #一号小车控制
                if input_cmd == "1":
                    handle_cmd_select("1", "/task 2")
                elif input_cmd == "2":
                    handle_cmd_select("1", "/task 3")
                elif input_cmd == "3":
                    handle_cmd_select("1", "/task 4")
                elif input_cmd == ".":
                    handle_cmd_select("1", "/task 5")
                #二号小车控制
                if input_cmd == "4":
                    handle_cmd_select("2", "/task 2")
                elif input_cmd == "5":
                    handle_cmd_select("2", "/task 3")
                elif input_cmd == "6":
                    handle_cmd_select("2", "/task 4")
                elif input_cmd == "+":
                    handle_cmd_select("2", "/task 5")
                #三号小车控制
                if input_cmd == "7":
                    handle_cmd_select("2", "/task 2")
                elif input_cmd == "8":
                    handle_cmd_select("2", "/task 3")
                elif input_cmd == "9":
                    handle_cmd_select("2", "/task 4")
                elif input_cmd == "-":
                    handle_cmd_select("2", "/task 5")

                #特殊触发事件
                if input_cmd == "/power_low":
                    handle_cmd_select("2", "/task 6")
                if input_cmd == "/ID":
                    handle_cmd_select("3", "/task 3")
                    handle_cmd_select("2", "/task 4")
                    handle_cmd_select("1", "/task 7") #这个点位还没定


    except KeyboardInterrupt:
        server.stop()
        broadcaster.stop()
        log_up.close()
        log_down.close()



