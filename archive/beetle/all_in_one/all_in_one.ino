#include <EEPROM.h>
#include "CRC8.h"

// Packet Types
#define SYN 'S'
#define ACK 'A'
#define UPDATE 'U'
#define DATA 'D'
#define SHOOT 'G'
#define KICK 'K'
#define INVALID_PACKET 'X'

struct PlayerState {
  uint8_t updateSeq = 99;
  uint8_t audio = 0;
  uint8_t reload = 0;
  uint8_t bullet = 6; //-> Store in EEPROM instead
};

struct AckPacket {
  char packetType = ACK;
  uint8_t seq = 0;
  byte padding[17] = {0};
  uint8_t crc;
};

struct ShootPacket {
  char packetType = SHOOT;
  uint8_t seq = 0;
  uint8_t hit = 0;
  uint8_t bullet = 0;
  byte padding[15] = {0};
  uint8_t crc;
};

struct KickPacket {
  char packetType = KICK;
  uint8_t seq = 0;
  byte padding[17] = {0};
  uint8_t crc;
};

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
};

PlayerState playerState;
AckPacket ackPacket;
ShootPacket shootPacket;
DataPacket dataPacket;
KickPacket kickPacket;
CRC8 crc;
uint8_t globalSeq = 0;
bool isHandshaking = false; // track re-handshake case during handshake
bool isHandshaked = false;
bool isWaitingForAck = false;
int waitingAckSeq;
int bulletAddr = 0;
unsigned long previousDataMillis = 0;
unsigned long previousShootMillis = 0; 
unsigned long previousKickMillis = 0;

void getShootPacket() {
  shootPacket.seq = ++globalSeq;
  shootPacket.hit = random(0, 2);
  shootPacket.bullet = playerState.bullet;
  //shootPacket.bullet = EEPROM.read(bulletAddr);
  crc.reset();
  crc.add((byte *) &shootPacket, sizeof(shootPacket) - 1);
  shootPacket.crc = crc.calc();
}

void getKickPacket() {
  kickPacket.seq = ++globalSeq;
  crc.reset();
  crc.add((byte *) &kickPacket, sizeof(kickPacket) - 1);
  kickPacket.crc = crc.calc();
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

void sendKICK() {
  Serial.write((byte *) &kickPacket, sizeof(kickPacket));
}

void handshake(uint8_t seq) {
  sendACK(seq);
  isHandshaked = false;
  waitAck(500, seq);
  if (!isWaitingForAck) { 
    isHandshaked = true;
  }
}

void waitAck(int ms, uint8_t seq) {  // wait for ACK, timeout
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
    // update from server have higher priority than sending data to relay 
    // DATA > UPDATE > SHOOT
    case UPDATE:
      sendACK(seqReceived);

      // only update if it's the new seq number
      if (playerState.updateSeq != seqReceived) {
        playerState.updateSeq = buffer[1];
        playerState.audio = buffer[2];
        playerState.reload = buffer[3];
        playerState.bullet = buffer[4];
        //EEPROM.update(bulletAddr, buffer[4]);
      }
      // might wanna reset the audio and reload after the audio is played
      break;
    
    case SYN:
      // start of handshake
      handshake(seqReceived);
      break;

    case ACK:
      //check seq otherwise ignore ACK
      if (waitingAckSeq == seqReceived) {
        isWaitingForAck = false;
      }
      break;

    default:
      //discard invalid packet
      break;
  }
  return packetType;
}

void setup() {
  Serial.begin(115200);
}

int shootRand = random(2000, 8000);
int actionRand = random(10000, 15000);
int kickRand = random(3000, 8000);

void loop() {
  unsigned long currentMillis = millis();

  if (Serial.available() >= 20) {
    handleRxPacket();
  }

  if ((currentMillis - previousShootMillis >= shootRand) && isHandshaked) {
    getShootPacket();
    do {
      sendSHOOT();
      isWaitingForAck = true;
      waitAck(500, shootPacket.seq);
    } while (isWaitingForAck);

    shootRand = random(2000, 8000);
    previousShootMillis = currentMillis;
  }

  if ((currentMillis - previousShootMillis >= kickRand) && isHandshaked) {
    getKickPacket();
    do {
      sendKICK();
      isWaitingForAck = true;
      waitAck(500, kickPacket.seq);
    } while (isWaitingForAck);

    kickRand = random(3000, 8000);
    previousKickMillis = currentMillis;
  }

  else if ((currentMillis - previousDataMillis >= actionRand) && isHandshaked) {
    sendDATA();
    if (Serial.available() >= 20) {
      //clear the serial (ignored) wait relay to send them again, there could be the case where multiple 
      //of the same packets waiting in the buffer -> keep sending multiple ack to response
      String buffer = Serial.readString();
      buffer = "";
    }

    actionRand = random(7000, 15000);
    previousDataMillis = currentMillis;
  }
}
