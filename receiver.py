# v2
import datetime, time  # to calculate the time delta of packet transmission
import logging, sys  # to write the log
import socket  # Core lib, to send packet via UDP socket
from threading import Thread  # (Optional)threading will make the timer easily implemented
import random  # for flp and rlp function
from collections import defaultdict

BUFFERSIZE = 1000000



class Receiver:
    def __init__(self, receiver_port: int, sender_port: int, filename: str, flp: float, rlp: float) -> None:
        '''
        The server will be able to receive the file from the sender via UDP
        :param receiver_port: the UDP port number to be used by the receiver to receive PTP segments from the sender.
        :param sender_port: the UDP port number to be used by the sender to send PTP segments to the receiver.
        :param filename: the name of the text file into which the text sent by the sender should be stored
        :param flp: forward loss probability, which is the probability that any segment in the forward direction (Data, FIN, SYN) is lost.
        :param rlp: reverse loss probability, which is the probability of a segment in the reverse direction (i.e., ACKs) being lost.
        '''
        self.address = "127.0.0.1"  # change it to 0.0.0.0 or public ipv4 address if want to test it between different computers
        self.receiver_port = int(receiver_port)
        self.sender_port = int(sender_port)
        self.server_address = (self.address, self.receiver_port)
        self.filename = filename
        self.flp = flp
        self.rlp = rlp

        # init the UDP socket
        # define socket for the server side and bind address
        logging.debug(f"The sender is using the address {self.server_address} to receive message!")
        self.receiver_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        self.receiver_socket.bind(self.server_address)
        self.type_dict = {"DATA": 0, "ACK": 1, "SYN": 2, "FIN": 3, "RESET": 4}
        self.get_type_dict = {0: "DATA", 1: "ACK", 2: "SYN", 3: "FIN", 4: "RESET"}
        self.buffer = defaultdict(str)  # rev_seq_no : content
        self.start_time = time.time()
        # self.expected_seq_no = 0
        self.revno_expno_dict = {}  # rev_seq_no : next_expected_rev_seq_no
        self.all_rev_seqno = set()

    def run(self) -> None:
        counter = 0
        while True:

            # try to receive any incoming message from the sender
            try:
                incoming_message, sender_address = self.receiver_socket.recvfrom(BUFFERSIZE)
                rev_type_no = int.from_bytes(incoming_message[:2], byteorder='big')
                rev_seq_no = int.from_bytes(incoming_message[2:4], byteorder='big')
            except OSError:
                continue

            # rev SYN
            if rev_type_no == 2:
                # randomly drop SYN packets
                if random.randint(1, 100) < float(self.flp) * 100:
                    logging.warning("SYN packet dropped!")
                    continue
                counter += 1
                if counter == 1:
                    self.start_time = time.time()
                    logging.warning(f"rcv\t0\t{self.get_type_dict[rev_type_no]}\t{rev_seq_no}\t0")

                else:
                    time_diff = round((time.time() - self.start_time) * 1000, 2)
                    logging.warning(f"rcv\t{time_diff}\t{self.get_type_dict[rev_type_no]}\t{rev_seq_no}\t0")

                syn_msg = self.type_dict["ACK"].to_bytes(2, byteorder='big', signed=False) + \
                          (rev_seq_no + 1).to_bytes(2, byteorder='big', signed=False)
                time_diff = round((time.time() - self.start_time) * 1000, 2)
                logging.warning(f"snd\t{time_diff}\tACK\t{rev_seq_no + 1}\t0")

                # randomly drop ACK packets
                if random.randint(1, 100) < float(self.rlp) * 100:
                    logging.warning("ACKs packet dropped!")
                    continue
                else:
                    self.receiver_socket.sendto(syn_msg, sender_address)
                    self.expected_seq_no = rev_seq_no + 1

            # rev FIN
            elif rev_type_no == 3:
                # randomly drop FIN packets
                if random.randint(1, 100) < float(self.flp) * 100:
                    logging.warning("FIN packet dropped!")
                    continue
                time_diff = round((time.time() - self.start_time) * 1000, 2)
                logging.warning(f"rcv\t{time_diff}\t{self.get_type_dict[rev_type_no]}\t{rev_seq_no}\t0")

                syn_msg = self.type_dict["ACK"].to_bytes(2, byteorder='big', signed=False) + \
                          (rev_seq_no + 1).to_bytes(2, byteorder='big', signed=False)
                time_diff = round((time.time() - self.start_time) * 1000, 2)
                logging.warning(f"snd\t{time_diff}\tACK\t{rev_seq_no + 1}\t0")
                # randomly drop ACK packets
                if random.randint(1, 100) < float(self.rlp) * 100:
                    logging.warning("ACKs packet dropped!")
                    continue
                else:
                    self.receiver_socket.sendto(syn_msg, sender_address)
                    logging.debug("socket closed")
                    self.receiver_socket.close()


            # rev DATA
            elif rev_type_no == 0:
                # randomly drop data packets
                if random.randint(1, 100) < float(self.flp) * 100:
                    logging.warning(f"DATA {rev_seq_no} packet dropped!")
                    continue

                with open(self.filename, "a") as file:
                    content = incoming_message[4:].decode()
                    length = len(content)
                    time_diff = round((time.time() - self.start_time) * 1000, 2)
                    logging.warning(f"rcv\t{time_diff}\t{self.get_type_dict[rev_type_no]}{rev_seq_no}\t{length}")
                    self.revno_expno_dict[rev_seq_no] = (rev_seq_no + length) % 65535

                    if rev_seq_no not in self.all_rev_seqno:
                        self.all_rev_seqno.add(rev_seq_no)
                        self.buffer[rev_seq_no] = content
                    while self.expected_seq_no in self.buffer:
                        file.write(self.buffer[self.expected_seq_no])
                        del self.buffer[self.expected_seq_no]
                        self.expected_seq_no = self.revno_expno_dict[self.expected_seq_no]

                # reply "ACK"
                ack_seq_no = self.expected_seq_no
                reply_message = self.type_dict["ACK"].to_bytes(2, byteorder='big', signed=False) + \
                                ack_seq_no.to_bytes(2, byteorder='big', signed=False)
                time_diff = round((time.time() - self.start_time) * 1000, 2)
                logging.warning(f"snd\t{time_diff}\tACK\t{ack_seq_no}\t0")

                # randomly drop ACK packets
                if random.randint(1, 100) < float(self.rlp) * 100:
                    logging.warning("ACKs packet dropped!")
                    continue
                else:
                    self.receiver_socket.sendto(reply_message, sender_address)

            # rev RESET
            elif rev_type_no == 4:
                time_diff = round((time.time() - self.start_time) * 1000, 2)
                logging.warning(f"rcv\t{time_diff}\t{self.get_type_dict[rev_type_no]}\t{rev_seq_no}\t0")

                logging.debug("Socket closed!")
                self.receiver_socket.close()


        


if __name__ == '__main__':
    logging.basicConfig(
        filename="Receiver_log.txt",
        # stream=sys.stderr,
        level=logging.WARNING,
        format='%(asctime)s,%(msecs)03d %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d:%H:%M:%S')

    if len(sys.argv) != 6:
        print(
            "\n===== Error usage, python3 receiver.py receiver_port sender_port FileReceived.txt flp rlp ======\n")
        exit(0)

    receiver = Receiver(*sys.argv[1:])
    receiver.run()
