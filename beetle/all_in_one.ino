/*
  ltr:
  - seq number
  - CRC
  - update the packet structure
  - separate vest, hand, leg
  - re-handshake when too many checksum wrong or ACK missing
  - (for consideration) : reset one of the beetle, (ble is not disconnected but all the data hold on beetle is reset)
  - resend bullet data when reestablish connection
  - pass data to ultra96


  curr:
  - handshake + re-handshake when disconnect
  - ack timeout, resend
  - can handle fragmentation
  - support kick, shoot, update, data, syn, ack
  - sending random data
*/

// Packet Types
#define SYN 'S'
#define ACK 'A'
#define UPDATE 'U'
#define DATA 'D'
#define SHOOT 'G'
#define KICK 'K'
#define INVALID_PACKET 'X'

#define P1_VEST 1
#define P1_HAND 2
#define P1_LEG  3
#define P2_VEST 4
#define P2_HAND 5
#define P2_LEG  6
#define DEVICE_ID 2

struct PlayerState {
  uint8_t audio = 0;
  uint8_t reload = 0;
  uint8_t bullet = 6;
};

struct AckPacket {
  char packetType = ACK;
  byte padding[19] = {0};
};

struct ShootPacket {
  char packetType = SHOOT;
  uint8_t deviceID = DEVICE_ID;
  uint8_t hit = 0;
  uint8_t bullet = 0;
  byte padding[16] = {0};
};

struct KickPacket {
  char packetType = KICK;
  uint8_t deviceID = DEVICE_ID;
  byte padding[18] = {0};
};

struct DataPacket{
  char packetType = DATA;
  uint8_t deviceID = DEVICE_ID;
  uint8_t seq;
  int16_t accX;
  int16_t accY;
  int16_t accZ;
  int16_t gyrX;
  int16_t gyrY;
  int16_t gyrZ;
  byte padding[5] = {0};
};

String buffer;
PlayerState playerState;
AckPacket ackPacket;
ShootPacket shootPacket;
DataPacket dataPacket;
KickPacket kickPacket;

bool isHandshaking = false; // track re-handshake case
bool isHandshaked = false;
bool isWaitingForAck = false;

void getShootPacket() {
  shootPacket.hit = random(0, 2);
  shootPacket.bullet = playerState.bullet;
}

void getDataPacket(uint8_t seq) {
  dataPacket.seq = seq;
  dataPacket.accX = random(-10000, 10000);
  dataPacket.accY = random(-10000, 10000);
  dataPacket.accZ = random(-10000, 10000);
  dataPacket.gyrX = random(-10000, 10000);
  dataPacket.gyrY = random(-10000, 10000);
  dataPacket.gyrZ = random(-10000, 10000);
}

void sendACK() {
  Serial.write((byte *) &ackPacket, sizeof(ackPacket));
}

void sendDATA() {
  for (uint8_t seq = 0; seq < 40; seq++) {
    getDataPacket(seq);
    Serial.write((byte *) &dataPacket, sizeof(dataPacket));
    delay(50);
  }
}

void sendSHOOT() {
  Serial.write((byte *) &shootPacket, sizeof(shootPacket));
}

void sendKICK() {
  Serial.write((byte *) &kickPacket, sizeof(kickPacket));
}

// void updatePlayerState() {
//   Serial.println(buffer);
//   playerState.audio = buffer[2] - '0';
//   playerState.reload = buffer[3] - '0';
//   playerState.bullet = buffer[4] - '0';
  
// }

void handshake() {
  sendACK();
  isHandshaked = false;
  waitAck(500);
  if (!isWaitingForAck) { 
    isHandshaked = true;
  }
}

char handleRxPacket() { // TODO: checksum + seq check
  //buffer = "";
  String serialBuffer = Serial.readString();
  char packetType;

  while (serialBuffer.length() >= 20) {
    String buffer = serialBuffer.substring(0, 20); // Get the first 20 characters
    char packetType = char(buffer[0]);
    switch (packetType) {
      // update from server have higher priority than sending data to relay 
      // DATA(can be ignored by server) > UPDATE > SHOOT
      case UPDATE:
        playerState.audio = buffer[2] - '0';
        playerState.reload = buffer[3] - '0';
        playerState.bullet = buffer[4] - '0';
        sendACK();
        // might wanna reset the audio and reload after the audio is played
        break;
      
      case SYN:             // start of handshake
        handshake();       // isWaitingForAck = false;  for the re-handshake case
        break;

      case ACK:
        isWaitingForAck = false;
        break;

      default:
        //discard invalid packet
        break;
    }
    serialBuffer = serialBuffer.substring(20); // Remove the processed chunk from the string
  }
  return packetType;
}

void waitAck(int ms) {  // wait for ACK, timeout
  for (int i = 0; i < ms; i++) {
    if (Serial.available()) {
      handleRxPacket();
      return;
    }
    delay(1);
  }
}

/*void parsePacket(char packetType) {
  switch (packetType) {
    case UPDATE:
      sendACK();
      updatePlayerData();
      break;
    
    case SYN:                   // start of handshake
      handshake();
      break;

    default:
      break;

  }
}*/

void setup() {
  Serial.begin(115200);
}

void loop() {
  if (Serial.available()) {
    handleRxPacket();
  }
    
  int isKick = random(0,10000); 
  int isShoot = random(0,10000);
  int isAction = random(0,10000);

  if (isHandshaked && (isAction == 100)) { //trigger by IMU && isHandshaked
    sendDATA();
    if (Serial.available()) { //clear the serial (ignored) wait relay to send them again
      buffer = Serial.readString();
      buffer = "";
    }
  }
  
  else if (isHandshaked && (isShoot == 4)) { //trigger by the button && isHandshaked (if bullet > 0, bullet - 1)
    getShootPacket();
    do {
      sendSHOOT();
      isWaitingForAck = true;
      waitAck(500);
    } while (isWaitingForAck);
  }

  else if (isHandshaked && (isKick == 4)) { //trigger by flex sensor && isHandshaked  
    do {
      sendKICK();
      isWaitingForAck = true;
      waitAck(500);
    } while (isWaitingForAck);  
  }
}

