#include <EEPROM.h>
#include "CRC8.h"

#define SYN 'S'
#define SYNACK 'C'
#define ACK 'A'
#define UPDATE 'U'
#define DATA 'D'
#define SHOOT 'G'
#define INVALID_PACKET 'X'
#define NOT_WAITING_FOR_ACK -1
#define ACK_TIMEOUT 200

struct PlayerState {
  uint8_t updateSeq = 99;
  uint8_t bullet = 6; //-> Store in EEPROM instead
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

struct ShootPacket {
  char packetType = SHOOT;
  uint8_t seq = 0;
  uint8_t hit = 0;
  uint8_t bullet = 0;
  byte padding[15] = {0};
  uint8_t crc;
} shootPacket;

struct DataPacket{
  char packetType = DATA;
  uint8_t seq;
  int16_t accX;
  int16_t accY;
  int16_t accZ;
  int16_t gyrX;
  int16_t gyrY;
  int16_t gyrZ;
  byte padding[5] = {0};
  uint8_t crc;
} dataPacket;

struct AckTracker{
  int16_t synAck = -1;
  int16_t shootAck = -1;
} ackTracker;

CRC8 crc;
uint8_t globalSeq = 0;
int bulletAddr = 0;
bool isHandshaked = false;
unsigned long previousDataMillis = 0;
unsigned long previousShootMillis = 0; 

void getShootPacket() {
  shootPacket.seq = ++globalSeq;
  shootPacket.hit = random(0, 2);
  shootPacket.bullet = playerState.bullet;
  //shootPacket.bullet = EEPROM.read(bulletAddr);
  crc.reset();
  crc.add((byte *) &shootPacket, sizeof(shootPacket) - 1);
  shootPacket.crc = crc.calc();
}

void getDataPacket(uint8_t seq) {
  dataPacket.seq = seq;
  dataPacket.accX = random(-10000, 10000);
  dataPacket.accY = random(-10000, 10000);
  dataPacket.accZ = random(-10000, 10000);
  dataPacket.gyrX = random(-10000, 10000);
  dataPacket.gyrY = random(-10000, 10000);
  dataPacket.gyrZ = random(-10000, 10000);
  crc.reset();
  crc.add((byte *) &dataPacket, sizeof(dataPacket) - 1);
  dataPacket.crc = crc.calc();
}

void sendACK(uint8_t seq) {
  ackPacket.seq = seq;
  crc.reset();
  crc.add((byte *) &ackPacket, sizeof(ackPacket) - 1);
  ackPacket.crc = crc.calc();
  Serial.write((byte *) &ackPacket, sizeof(ackPacket));
}

void sendDATA() {
  for (uint8_t seq = 1; seq <= 100; seq++) {
    getDataPacket(seq);
    Serial.write((byte *) &dataPacket, sizeof(dataPacket));
    delay(20);
  }
}

void sendSHOOT() {
  Serial.write((byte *) &shootPacket, sizeof(shootPacket));
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
      waitAck(ACK_TIMEOUT);
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
        playerState.bullet = buffer[4];
        //EEPROM.update(bulletAddr, buffer[4]);
      }
      // might wanna reset the audio and reload after the audio is played
      break;
    
    case SYN:
      handshake(seqReceived);
      break;
    
    case SYNACK:
      ackTracker.synAck = NOT_WAITING_FOR_ACK;
      break;

    case ACK:
      if (ackTracker.shootAck == seqReceived) {
        ackTracker.shootAck = NOT_WAITING_FOR_ACK;
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

int shootRand = random(2000, 8000);
int actionRand = random(10000, 15000);

void loop() {
  unsigned long currentMillis = millis();

  if (Serial.available() >= 20) {
    handleRxPacket();
  }

  if ((currentMillis - previousShootMillis >= shootRand) && isHandshaked) {
    getShootPacket();
    do {
      sendSHOOT();
      ackTracker.shootAck = shootPacket.seq;
      waitAck(ACK_TIMEOUT);
    } while (ackTracker.shootAck != NOT_WAITING_FOR_ACK);

    shootRand = random(2000, 8000);
    previousShootMillis = currentMillis;
  }

  else if ((currentMillis - previousDataMillis >= actionRand) && isHandshaked) {
    sendDATA();
    if (Serial.available() >= 20) {
      String buffer = Serial.readString();
      buffer = "";
    }
    
    actionRand = random(10000, 15000);
    previousDataMillis = currentMillis;
  }
}
