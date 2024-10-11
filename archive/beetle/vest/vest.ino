#include "CRC8.h"

#define SYN 'S'
#define SYNACK 'C'
#define ACK 'A'
#define UPDATE 'U'
#define INVALID_PACKET 'X'
#define NOT_WAITING_FOR_ACK -1

struct PlayerState {
  uint8_t updateSeq = 99;
  uint8_t audio = 0;
  uint8_t reload = 0;
} playerState;

struct AckPacket {
  char packetType = ACK;
  uint8_t seq = 0;
  byte padding[17] = {0};
  uint8_t crc;
} ackPacket;

struct SynAckPacket {
  char packetType = SYNACK;
  uint8_t seq = 0;
  byte padding[17] = {0};
  uint8_t crc;
} synAckPacket;

struct AckTracker{
  int16_t synAck = -1;
  int16_t kickAck = -1;
} ackTracker;

CRC8 crc;
uint8_t globalSeq = 0;
bool isHandshaked = false;
int timeout = 200;

void sendACK(uint8_t seq) {
  ackPacket.seq = seq;
  crc.reset();
  crc.add((byte *) &ackPacket, sizeof(ackPacket) - 1);
  ackPacket.crc = crc.calc();
  Serial.write((byte *) &ackPacket, sizeof(ackPacket));
}

void sendSYNACK() {
  crc.reset();
  crc.add((byte *) &synAckPacket, sizeof(synAckPacket) - 1);
  synAckPacket.crc = crc.calc();
  Serial.write((byte *) &synAckPacket, sizeof(synAckPacket));
}

void handshake(uint8_t seq) {
 isHandshaked = false;
  do {
      sendSYNACK();
      ackTracker.synAck = seq;
      waitAck(timeout);
    } while (ackTracker.synAck != NOT_WAITING_FOR_ACK);
  
  isHandshaked = true;
}
void waitAck(int ms) {
  for (int i = 0; i < ms; i++) {
    if (Serial.available() >= 20) {
      char packetTypeRx = handleRxPacket();
      if (packetTypeRx == ACK || packetTypeRx == SYNACK){
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
    case UPDATE:
      sendACK(seqReceived);
      if (playerState.updateSeq != seqReceived) {
        playerState.updateSeq = buffer[1];
        playerState.audio = buffer[2];
        playerState.reload = buffer[3];
      }
      // might wanna reset the audio and reload after the audio is played
      break;
    
    case SYN:
      handshake(seqReceived);
      break;

    case SYNACK:
      ackTracker.synAck = NOT_WAITING_FOR_ACK;
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
}
