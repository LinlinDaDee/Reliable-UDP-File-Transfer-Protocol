# v2
import datetime, time  # to calculate the time delta of packet transmission
import logging, sys  # to write the log
import socket  # Core lib, to send packet via UDP socket
import threading  # (Optional)threading will make the timer easily implemented
from threading import Thread, Lock
import random
import select
from collections import defaultdict, deque
BUFFERSIZE = 1024

class Sender:
    def __init__(self, sender_port: int, receiver_port: int, filename: str, max_win: int, rot: int) -> None:
        '''
        The Sender will be able to connect the Receiver via UDP
        :param sender_port: the UDP port number to be used by the sender to send PTP segments to the receiver
        :param receiver_port: the UDP port number on which receiver is expecting to receive PTP segments from the sender
        :param filename: the name of the text file that must be transferred from sender to receiver using your reliable transport protocol.
        :param max_win: the maximum window size in bytes for the sender window.
        :param rot: the value of the retransmission timer in milliseconds. This should be an unsigned integer.
        '''
        self.sender_port = int(sender_port)
        self.receiver_port = int(receiver_port)
        self.sender_address = ("127.0.0.1", self.sender_port)
        self.receiver_address = ("127.0.0.1", self.receiver_port)
        self.filename = filename
        self.max_win = max_win
        self.rot = rot

        # init the UDP socket
        logging.debug(f"The sender is using the address {self.sender_address}")
        self.sender_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        self.sender_socket.bind(self.sender_address)
        self.timeout = int(self.rot) / 1000
        self.type_dict = {"DATA": 0, "ACK": 1, "SYN": 2, "FIN": 3, "RESET": 4}
        self.get_type_dict = {0: "DATA", 1: "ACK", 2: "SYN", 3: "FIN", 4: "RESET"}

        self._is_active = True  # for the multi-threading
        self.SYN_acked = False
        self.FIN_acked = False
        self.seq_content_dic = defaultdict(str)  # seq : file_content(str)
        self.retrans_counter = defaultdict(int)  # seq : retrans_time
        # self.seq_unacked_dic = defaultdict(tuple)  # seq : (msg, time.time()) msg is in b
        self.seq_contlen_dic = {}  # seq : file_content_length
        self.expected_ACK_dic = {}  # seq_no : expected_ACK_no
        self.num_seqno_dic = {}  # 0/1/2/3 : seq_no ...
        self.seqno_num_dic = {}  # seq_no : 0/1/2/3...
        self.data_acked = False
        #self.seq_ack_times = {}

        self.acked_seq = set()  # result shared for all sub-thread

        self.send_counter = 0


        self.sent_queue = deque()

        self.lock = Lock()



    def ptp_open_and_send(self):

        self.sender_socket.settimeout(self.timeout)
        dup = 3
        # sequence_number = 1000
        sequence_number = random.randint(0, 65535)

        self.start_time = time.time()

        # SYN
        while dup > 0:
            msg = self.type_dict["SYN"].to_bytes(2, byteorder='big', signed=False) + \
                  sequence_number.to_bytes(2, byteorder='big', signed=False)
            self.sender_socket.sendto(msg, self.receiver_address)
            self.send_counter += 1
            time_diff = round((time.time() - self.start_time) * 1000, 2)
            if dup == 3:
                logging.warning(f"snd\t0\tSYN\t{sequence_number}\t0")
            else:
                logging.warning(f"snd\t{time_diff}\tSYN\t{sequence_number}\t0")
            self.listen(sequence_number)
            if self.SYN_acked:
                break
            else:
                dup -= 1
                logging.warning(f"Timeout! Resend the SYN, resent chances left:{dup}")
        if dup == 0:
            type = 4
            no = 0
            logging.warning("connected failed! Reset the connection.")
            reset_msg = type.to_bytes(2, byteorder='big', signed=False) + no.to_bytes(2, byteorder='big', signed=False)
            self.sender_socket.sendto(reset_msg, self.receiver_address)
            self.send_counter += 1
            time_diff = round((time.time() - self.start_time) * 1000, 2)
            logging.warning(f"snd\t{time_diff}\tRESET\t\t0\t0")
            self.ptp_close()
            logging.warning("returned to the CLOSED state")

        # DATA
        else:
            sequence_number += 1
            with open(self.filename, "r") as file:
                packets_num = 0
                while True:
                    content = file.read(1000)
                    if content:
                        self.seq_content_dic[sequence_number] = content
                        length = len(content)
                        self.seq_contlen_dic[sequence_number] = length
                        self.num_seqno_dic[packets_num] = sequence_number
                        self.seqno_num_dic[sequence_number] = packets_num
                        self.expected_ACK_dic[sequence_number] = (sequence_number + length) % 65535
                        sequence_number = (sequence_number + length) % 65535
                        packets_num += 1
                    else:
                        break
            self.fin_seq = sequence_number

            win_seq = 0
            win_size_num = int(int(self.max_win) / 1000)

            # without sliding window
            if win_size_num == 1:
                for i in range(packets_num):
                    self.thread_send_and_listen(self.num_seqno_dic[i])
                    self.data_acked = False
                self.send_FIN()

            else:
                window = deque(maxlen=win_size_num)
                unacked_data = {}  # seq_no : num
                num_list = []
                for i in range(len(self.num_seqno_dic)):
                    num_list.append(i)

                win_step = []
                for i in range(0, len(num_list), win_size_num):
                    win_step.append(num_list[i:i + win_size_num])
                # logging.debug(f"win_step = {win_step}")

                try:
                    for j in range(len(win_step)):
                        threads = []
                        for i in range(len(win_step[j])):
                            sequence_number = self.num_seqno_dic[i + j * win_size_num]
                            self.retrans_counter[sequence_number] = 0
                            t = Thread(target=self.thread_send_and_listen, args=(sequence_number,))
                            t.start()
                            threads.append(t)
                        for t in threads:
                            t.join()
                        self.data_acked = False
                except OSError:
                    self.ptp_close()

                self.send_FIN()



    def thread_send_and_listen_2(self, sequence_number):

        global send_time
        while not self.data_acked:
            msg = self.type_dict["DATA"].to_bytes(2, byteorder='big', signed=False) + \
                  sequence_number.to_bytes(2, byteorder='big', signed=False) + \
                  self.seq_content_dic[sequence_number].encode()
            if self.retrans_counter[sequence_number] == 0:
                send_time = time.time()

            while self.retrans_counter[sequence_number] < 3 and not self.data_acked:

                if self.retrans_counter[sequence_number] == 0 or (time.time() - send_time) > self.timeout:
                    self.lock.acquire()
                    self.sender_socket.sendto(msg, self.receiver_address)
                    self.lock.release()
                    self.send_counter += 1
                    time_diff = round((send_time - self.start_time) * 1000, 2)
                    logging.warning(f"snd\t{time_diff}\tDATA{sequence_number}\t{self.seq_contlen_dic[sequence_number]}")
                    self.retrans_counter[sequence_number] += 1

                try:
                    self.lock.acquire()
                    incoming_message, _ = self.sender_socket.recvfrom(BUFFERSIZE)
                    self.lock.release()
                    rev_type_no = int.from_bytes(incoming_message[:2], byteorder='big')
                    rev_ack_no = int.from_bytes(incoming_message[2:4], byteorder='big')
                    # self.seq_ack_times[rev_ack_no] += 1
                    if (rev_ack_no + 1) % 65535 == self.fin_seq + 1:
                        time_diff = round((time.time() - self.start_time) * 1000, 2)
                        logging.warning(f"rcv\t{time_diff}\t{self.get_type_dict[rev_type_no]}\t{rev_ack_no}\t0")
                        self.data_acked = True
                        break
                    if rev_ack_no == self.expected_ACK_dic[sequence_number]:
                        time_diff = round((time.time() - self.start_time) * 1000, 2)
                        logging.warning(f"rcv\t{time_diff}\t{self.get_type_dict[rev_type_no]}\t{rev_ack_no}\t0")
                        self.data_acked = True
                        break
                    if self.seqno_num_dic[rev_ack_no] > self.seqno_num_dic[self.expected_ACK_dic[sequence_number]]:
                        self.data_acked = True
                        break
                    if self.seqno_num_dic[rev_ack_no] < self.seqno_num_dic[self.expected_ACK_dic[sequence_number]]:
                        time_diff = round((time.time() - self.start_time) * 1000, 2)
                        logging.warning(f"rcv\t{time_diff}\t{self.get_type_dict[rev_type_no]}\t{rev_ack_no}\t0")
                except socket.timeout:
                    logging.warning(f"Timeout! Resend the DATA seq={sequence_number}, resent chances left:{3 - self.retrans_counter[sequence_number]}")
                    continue

            if self.retrans_counter[sequence_number] == 3:
                type = 4
                no = 0
                logging.warning("connected failed! Reset the connection.")
                reset_msg = type.to_bytes(2, byteorder='big', signed=False) + no.to_bytes(2, byteorder='big', signed=False)
                self.sender_socket.sendto(reset_msg, self.receiver_address)
                self.send_counter += 1
                time_diff = round((time.time() - self.start_time) * 1000, 2)
                logging.warning(f"snd\t{time_diff}\tRESET\t\t0\t0")
                self._is_active = False  # close the sub-thread
                self.sender_socket.close()
                logging.warning("returned to the CLOSED state")



    def thread_send_and_listen(self, sequence_number):

        while not self.data_acked:
            msg = self.type_dict["DATA"].to_bytes(2, byteorder='big', signed=False) + \
                  sequence_number.to_bytes(2, byteorder='big', signed=False) + \
                  self.seq_content_dic[sequence_number].encode()
            # 1st send
            if self.retrans_counter[sequence_number] == 0:
                send_time = time.time()

                try:
                    self.sender_socket.sendto(msg, self.receiver_address)
                except OSError:
                    break

                self.send_counter += 1
                time_diff = round((send_time - self.start_time) * 1000, 2)
                logging.warning(f"snd\t{time_diff}\tDATA{sequence_number}\t{self.seq_contlen_dic[sequence_number]}")
                self.retrans_counter[sequence_number] += 1
                try:

                    incoming_message, _ = self.sender_socket.recvfrom(BUFFERSIZE)

                    rev_type_no = int.from_bytes(incoming_message[:2], byteorder='big')
                    rev_ack_no = int.from_bytes(incoming_message[2:4], byteorder='big')

                    if (rev_ack_no + 1) % 65535 == self.fin_seq + 1:
                        time_diff = round((time.time() - self.start_time) * 1000, 2)
                        logging.warning(f"rcv\t{time_diff}\t{self.get_type_dict[rev_type_no]}\t{rev_ack_no}\t0")
                        self.data_acked = True
                        return

                    if rev_ack_no == self.expected_ACK_dic[sequence_number]:
                        time_diff = round((time.time() - self.start_time) * 1000, 2)
                        logging.warning(f"rcv\t{time_diff}\t{self.get_type_dict[rev_type_no]}\t{rev_ack_no}\t0")
                        self.data_acked = True

                        self.acked_seq.add(sequence_number)

                    try:
                        if self.seqno_num_dic[rev_ack_no] > self.seqno_num_dic[self.expected_ACK_dic[sequence_number]]:
                            time_diff = round((time.time() - self.start_time) * 1000, 2)
                            logging.warning(f"rcv\t{time_diff}\t{self.get_type_dict[rev_type_no]}\t{rev_ack_no}\t0")
                            self.data_acked = True

                            self.acked_seq.add(sequence_number)
                    except KeyError:
                        continue

                    if self.seqno_num_dic[rev_ack_no] < self.seqno_num_dic[self.expected_ACK_dic[sequence_number]]:
                        time_diff = round((time.time() - self.start_time) * 1000, 2)
                        logging.warning(f"rcv\t{time_diff}\t{self.get_type_dict[rev_type_no]}\t{rev_ack_no}\t0")
                except socket.timeout:
                    # 2nd
                    logging.warning(f"Timeout! Resend the DATA seq={sequence_number}, resent chances left:{3 - self.retrans_counter[sequence_number]}")

                    self.sender_socket.sendto(msg, self.receiver_address)

                    self.send_counter += 1
                    time_diff = round((time.time() - self.start_time) * 1000, 2)
                    logging.warning(f"snd\t{time_diff}\tDATA{sequence_number}\t{self.seq_contlen_dic[sequence_number]}")
                    self.retrans_counter[sequence_number] += 1
                    try:

                        incoming_message, _ = self.sender_socket.recvfrom(BUFFERSIZE)

                        rev_type_no = int.from_bytes(incoming_message[:2], byteorder='big')
                        rev_ack_no = int.from_bytes(incoming_message[2:4], byteorder='big')
                       # self.seq_ack_times[rev_ack_no] += 1
                        if (rev_ack_no + 1) % 65535 == self.fin_seq + 1:
                            time_diff = round((time.time() - self.start_time) * 1000, 2)
                            logging.warning(f"rcv\t{time_diff}\t{self.get_type_dict[rev_type_no]}\t{rev_ack_no}\t0")
                            self.data_acked = True
                            return
                       # self.seq_ack_times[rev_ack_no] += 1

                        if rev_ack_no == self.expected_ACK_dic[sequence_number]:
                            time_diff = round((time.time() - self.start_time) * 1000, 2)
                            logging.warning(f"rcv\t{time_diff}\t{self.get_type_dict[rev_type_no]}\t{rev_ack_no}\t0")
                            self.data_acked = True

                            self.acked_seq.add(sequence_number)

                        if self.seqno_num_dic[rev_ack_no] > self.seqno_num_dic[self.expected_ACK_dic[sequence_number]]:
                            self.data_acked = True

                            self.acked_seq.add(sequence_number)

                        if self.seqno_num_dic[rev_ack_no] < self.seqno_num_dic[self.expected_ACK_dic[sequence_number]]:
                            time_diff = round((time.time() - self.start_time) * 1000, 2)
                            logging.warning(f"rcv\t{time_diff}\t{self.get_type_dict[rev_type_no]}\t{rev_ack_no}\t0")
                    except socket.timeout:
                        # 3rd
                        logging.warning(
                            f"Timeout! Resend the DATA seq={sequence_number}, resent chances left:{3 - self.retrans_counter[sequence_number]}")

                        self.sender_socket.sendto(msg, self.receiver_address)

                        self.send_counter += 1
                        time_diff = round((time.time() - self.start_time) * 1000, 2)
                        logging.warning(
                            f"snd\t{time_diff}\tDATA{sequence_number}\t{self.seq_contlen_dic[sequence_number]}")
                        self.retrans_counter[sequence_number] += 1
                        try:

                            try:
                                incoming_message, _ = self.sender_socket.recvfrom(BUFFERSIZE)
                            except OSError:
                                break

                            rev_type_no = int.from_bytes(incoming_message[:2], byteorder='big')
                            rev_ack_no = int.from_bytes(incoming_message[2:4], byteorder='big')
                            # self.seq_ack_times[rev_ack_no] += 1
                            if (rev_ack_no + 1) % 65535 == self.fin_seq + 1:
                                time_diff = round((time.time() - self.start_time) * 1000, 2)
                                logging.warning(f"rcv\t{time_diff}\t{self.get_type_dict[rev_type_no]}\t{rev_ack_no}\t0")
                                self.data_acked = True
                                return
                          #  self.seq_ack_times[rev_ack_no] += 1

                            if rev_ack_no == self.expected_ACK_dic[sequence_number]:
                                time_diff = round((time.time() - self.start_time) * 1000, 2)
                                logging.warning(f"rcv\t{time_diff}\t{self.get_type_dict[rev_type_no]}\t{rev_ack_no}\t0")
                                self.data_acked = True


                                self.acked_seq.add(sequence_number)
                            try:
                                if self.seqno_num_dic[rev_ack_no] > self.seqno_num_dic[
                                    self.expected_ACK_dic[sequence_number]]:
                                    self.data_acked = True

                                    self.acked_seq.add(sequence_number)
                            except KeyError:
                                continue

                            if self.seqno_num_dic[rev_ack_no] < self.seqno_num_dic[
                                self.expected_ACK_dic[sequence_number]]:
                                time_diff = round((time.time() - self.start_time) * 1000, 2)
                                logging.warning(f"rcv\t{time_diff}\t{self.get_type_dict[rev_type_no]}\t{rev_ack_no}\t0")
                        except socket.timeout:
                            type = 4
                            no = 0
                            logging.warning("connected failed! Reset the connection.")
                            reset_msg = type.to_bytes(2, byteorder='big', signed=False) + no.to_bytes(2, byteorder='big', signed=False)
                            self.sender_socket.sendto(reset_msg, self.receiver_address)
                            self.send_counter += 1
                            time_diff = round((time.time() - self.start_time) * 1000, 2)
                            logging.warning(f"snd\t{time_diff}\tRESET\t\t0\t0")
                            self._is_active = False  # close the sub-thread
                            self.sender_socket.close()
                            logging.warning("returned to the CLOSED state")





    def listen(self, sequence_number):
        while self._is_active:
            data, _, _ = select.select([self.sender_socket], [], [], self.timeout)

            try:
                if data:
                    incoming_message, _ = self.sender_socket.recvfrom(BUFFERSIZE)
                    rev_type_no = int.from_bytes(incoming_message[:2], byteorder='big')
                    rev_ack_no = int.from_bytes(incoming_message[2:4], byteorder='big')
                    time_diff = round((time.time() - self.start_time) * 1000, 2)
                    logging.warning(f"rcv\t{time_diff}\t{self.get_type_dict[rev_type_no]}\t{rev_ack_no}\t0")
                    if rev_ack_no == sequence_number + 1:
                        if not self.SYN_acked:
                            self.SYN_acked = True
                            break
                        if self.SYN_acked and not self.FIN_acked:
                            self.FIN_acked = True
                            break
                else:
                    break
            except:
                continue


    # FIN
    def send_FIN(self):
        try:
            dup = 3
            while dup > 0:
                msg = self.type_dict["FIN"].to_bytes(2, byteorder='big', signed=False) + \
                      self.fin_seq.to_bytes(2, byteorder='big', signed=False)
                self.sender_socket.sendto(msg, self.receiver_address)
                self.send_counter += 1
                time_diff = round((time.time() - self.start_time) * 1000, 2)
                logging.warning(f"snd\t{time_diff}\tFIN\t{self.fin_seq}\t0")
                self.listen(self.fin_seq)
                if self.FIN_acked:
                    self.ptp_close()
                    logging.debug("socket closed")
                    break
                else:
                    dup -= 1
                    logging.warning(f"Timeout! Resend the FIN, resent chances left:{dup}")
            if dup == 0:
                type = 4
                no = 0
                logging.warning("connected failed! Reset the connection.")
                reset_msg = type.to_bytes(2, byteorder='big', signed=False) + no.to_bytes(2, byteorder='big', signed=False)
                self.sender_socket.sendto(reset_msg, self.receiver_address)
                self.send_counter += 1
                time_diff = round((time.time() - self.start_time) * 1000, 2)
                logging.warning(f"snd\t{time_diff}\tRESET\t\t0\t0")
                self.ptp_close()
                logging.warning("returned to the CLOSED state")
        except OSError:
            self.ptp_close()


    def ptp_close(self):
        time.sleep(2)
        self._is_active = False  # close the sub-thread
        self.sender_socket.close()
        # logging.debug(f"send_counter = {self.send_counter}")


    def run(self):
        self.ptp_open_and_send()
        # if self._is_active:
        #     self.send_FIN()
        self.ptp_close()


if __name__ == '__main__':
    logging.basicConfig(
        filename="Sender_log.txt",
        # stream=sys.stderr,
        level=logging.WARNING,
        format='%(asctime)s,%(msecs)03d %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d:%H:%M:%S')

    if len(sys.argv) != 6:
        print(
            "\n===== Error usage, python3 sender.py sender_port receiver_port FileReceived.txt max_win rot ======\n")
        exit(0)

    sender = Sender(*sys.argv[1:])

    sender.run()

