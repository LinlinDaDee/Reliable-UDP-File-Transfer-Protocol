# Reliable-UDP-File-Transfer-Protocol
## Overview
This project implements a reliable file transfer protocol using UDP. The protocol ensures successful transmission of a file from a sender to a receiver, handling packet loss and retransmissions. 
## Sender.py
1. ptp_open_and_send:
- Establishes the connection with the receiver.
- Sends file data in packets using a sliding window protocol.
- Sends a SYN packet to the receiver and waits for an ACK.
- Retransmits SYN packets up to three times if no ACK is received.
- Terminates the connection and sends a RESET packet if no response is received after three attempts.
- Reads the text file and sends it via the sliding window protocol.
2. thread_send_and_listen:
- A multi-threaded method that sends data packets and listens for acknowledgments.
- Sends packets in the same window independently through each sub-thread, which may arrive out of order.
- Keeps track of sequence numbers of unacknowledged packets and retransmits them up to three times if a timeout occurs.
- Terminates the connection and sends a RESET packet if no response is received after three attempts.
3. Listen:
- Listens for incoming SYN/FIN acknowledgments and updates the state accordingly.
4. send_FIN:
- Sends a FIN signal to indicate the end of the file transfer.
- Retransmits the FIN packet up to three times if not acknowledged.
- Terminates the connection and sends a RESET packet if no response is received after three attempts.
5. ptp_close:
- Closes the connection.
## Receiver.py
1. simulating the packet loss by using flp and rlp:
- Simulates packet loss to test the reliability of the protocol.
2. Received SYN packets:
- Generates an ACK packet and sends it back to the sender.
- Sets ACK_no = received seq_no + 1.
3. Received DATA packets:
- Checks if the packet has been received before and adds it to a buffer (a dictionary).
- Verifies if the sequence number is in order and writes the in-order content to a file.
- Sends an ACK packet to the sender to confirm receipt of all data before ACK_no.
4. Received FIN packets:
- Sends an ACK packet to the sender before closing the UDP socket.
- Sets ACK_no = received FIN_no + 1.
5. Received RESET packets:
- Closes the UDP socket.
