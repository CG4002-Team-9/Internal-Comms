#include "CRC8.h"

#define SYN 'S'
#define ACK 'A'
#define KICK 'K'
#define INVALID_PACKET 'X'

struct AckPacket {
  char packetType = ACK;
  uint8_t seq = 0;
  byte padding[17] = {0};
  uint8_t crc;
};

struct KickPacket {
  char packetType = KICK;
  uint8_t seq = 0;
  byte padding[17] = {0};
  uint8_t crc;
};

AckPacket ackPacket;
KickPacket kickPacket;
CRC8 crc;
uint8_t globalSeq = 0;
bool isHandshaking = false;
bool isHandshaked = false;
bool isWaitingForAck = false;
int waitingAckSeq;

void getKickPacket() {
  kickPacket.seq = ++globalSeq;
  if (globalSeq == 100) {
    globalSeq = 0;
  }
  crc.reset();
  crc.add((byte *) &kickPacket, sizeof(kickPacket) - 1);
  kickPacket.crc = crc.calc();
}

void sendKICK() {
  // fake checksum
  if (random(10) == 4) {
    kickPacket.crc = 0;
  }
  else {
    crc.reset();
    crc.add((byte *) &kickPacket, sizeof(kickPacket) - 1);
    kickPacket.crc = crc.calc();
  }
  Serial.write((byte *) &kickPacket, sizeof(kickPacket));
}

void sendACK(uint8_t seq) {
  ackPacket.seq = seq;
  crc.reset();
  crc.add((byte *) &ackPacket, sizeof(ackPacket) - 1);
  ackPacket.crc = crc.calc();
  Serial.write((byte *) &ackPacket, sizeof(ackPacket));
}

void handshake(uint8_t seq) {
  sendACK(seq);
  isHandshaked = false;
  waitAck(200, seq);
  if (!isWaitingForAck) { 
    isHandshaked = true;
  }
}

void waitAck(int ms, uint8_t seq) {
  waitingAckSeq = seq;
  for (int i = 0; i < ms; i++) {
    if (Serial.available() >= 20) {
      handleRxPacket();
      if (!isWaitingForAck) {
        return;
      }
    }
    delay(1);
  }
}

char handleRxPacket() {
  char buffer[20];
  Serial.readBytes(buffer, 20);

  uint8_t crcReceived = buffer[19];
  crc.reset();
  crc.add(buffer, 19);
  if (!(crc.calc() == crcReceived)) {
    return INVALID_PACKET;
  }
  
  char packetType = buffer[0];
  uint8_t seqReceived = buffer[1];  
  switch (packetType) {
    case SYN:
      handshake(seqReceived);
      break;

    case ACK:
      if (waitingAckSeq == seqReceived) {
        isWaitingForAck = false;
      }
      break;

    default:
      break;
  }
  return packetType;
}

void setup() {
  Serial.begin(115200);
}

void loop() {
  if (Serial.available() >= 20) {
    handleRxPacket();
  }

  if (isHandshaked) {
    getKickPacket();
    do {
      sendKICK();
      isWaitingForAck = true;
      waitAck(200, kickPacket.seq);
    } while (isWaitingForAck);
  }
}
