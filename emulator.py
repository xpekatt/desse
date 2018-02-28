import socket, traceback, struct, base64, random, cStringIO, zlib, select
from time import gmtime, strftime

from helpers import *

SERVER_PORT_BOOTSTRAP = 18000
SERVER_PORT_US = 18666
SERVER_PORT_EU = 18667
SERVER_PORT_JP = 18668

class ImpSock(object):
    def __init__(self, sc, name):
        self.sc = sc
        self.name = name
        self.recvdata = ""
        
    def recv(self, sz):
        data = self.sc.recv(sz)
        self.recvdata += data
        return data
    
    def close(self):
        self.sc.close()
        
    def sendall(self, data):
        self.sc.sendall(data)
        
    def recv_line(self):
        line = ""
        while True:
            c = self.recv(1)
            if len(c) == 0:
                print "DISCONNECT at line", repr(line)
                raise Exception("DISCONNECT")
            line += c
            if line.endswith("\r\n"):
                line = line[:-2]
                #print self.name, "received", repr(line)
                # debugwrite(self.name, repr(line))
                return line
            
    def recv_all(self, size):
        res = ""
        while len(res) < size:
            data = self.recv(size - len(res))
            if len(data) == 0:
                print "DISCONNECT", repr(res)
                raise Exception("DISCONNECT")
            res += data
            
        #print self.name, "received", repr(res)
        # debugwrite(self.name, repr(res))
        return res
            
    def recv_headers(self):
        headers = {}
        while True:
            line = self.recv_line()
            if len(line) == 0:
                break
            key, value = line.split(": ")
            headers[key] = value
            
        return headers
    
class SOSData(object):
    def __init__(self, params, sosID):
        self.sosID = sosID
        self.blockID = int(params["blockID"])
        self.characterID = params["characterID"]
        self.posx = float(params["posx"])
        self.posy = float(params["posy"])
        self.posz = float(params["posz"])
        self.angx = float(params["angx"])
        self.angy = float(params["angy"])
        self.angz = float(params["angz"])
        self.messageID = int(params["messageID"])
        self.mainMsgID = int(params["mainMsgID"])
        self.addMsgCateID = int(params["addMsgCateID"])
        self.playerInfo = params["playerInfo"]
        self.qwcwb = int(params["qwcwb"])
        self.qwclr = int(params["qwclr"])
        self.isBlack = int(params["isBlack"])
        self.playerLevel = int(params["playerLevel"])
        self.Xratings = (1, 2, 3, 4, 5) # S, A, B, C, D
        self.Xtotalsessions = 123
        
    def serialize(self):
        res = ""
        res += struct.pack("<I", self.sosID)
        res += self.characterID + "\x00"
        res += struct.pack("<fff", self.posx, self.posy, self.posz)
        res += struct.pack("<fff", self.angx, self.angy, self.angz)
        res += struct.pack("<III", self.messageID, self.mainMsgID, self.addMsgCateID)
        res += struct.pack("<I", 0) # unknown1
        for r in self.Xratings:
            res += struct.pack("<I", r)
        res += struct.pack("<I", 0) # unknown2
        res += struct.pack("<I", self.Xtotalsessions)
        res += self.playerInfo + "\x00"
        res += struct.pack("<IIb", self.qwcwb, self.qwclr, self.isBlack)
        
        return res

class Server(object):
    def __init__(self):
        self.ghosts = {}
        self.replayheaders = {}
        self.replaydata = {}
        
        self.activeSOS = {}
        self.SOSindex = 1
        self.playerSOS = {}
        self.playerPending = {}

        f = open("replayheaders.bin", "rb")
        while True:
            header = ReplayHeader()
            res = header.create(f)
            if not res:
                break
                
            if header.blockID not in self.replayheaders:
                self.replayheaders[header.blockID] = []
                
            if (header.messageID, header.mainMsgID, header.addMsgCateID) != (0, 0, 0):
                self.replayheaders[header.blockID].append(header)
                
        print "finished read replay headers"
        
        f = open("replaydata.bin", "rb")
        while True:
            ghostID = f.read(4)
            if len(ghostID) != 4:
                break
            ghostID = struct.unpack("<I", ghostID)[0]
            
            data = readcstring(f)
            
            self.replaydata[ghostID] = data
            
        print "finished read replay data"
                
    def run(self):
        servers = []
        for port in (SERVER_PORT_BOOTSTRAP, SERVER_PORT_US, SERVER_PORT_EU, SERVER_PORT_JP):
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(('', port))
            server.listen(5)
            servers.append(server)
        
        print "listening"

        while True:
            try:
                readable, _, _ = select.select(servers, [], [])
                ready_server = readable[0]
                serverport = ready_server.getsockname()[1]
                
                client_sock, client_addr = ready_server.accept()
                sc = ImpSock(client_sock, "client")
                
                req = sc.recv_line()
                print "got connect from", client_addr, "to", serverport, "request", repr(req)
                
                clientheaders = sc.recv_headers()
                        
                cdata = sc.recv_all(int(clientheaders["Content-Length"]))
                cdata = decrypt(cdata)
                
                if serverport == SERVER_PORT_BOOTSTRAP:
                    data = open("info.ss", "rb").read()
                    
                    res = self.prepare_response_bootstrap(data)
                else:
                    data = None
                    
                    if "login.spd" in req:
                        cmd, data = self.handle_login(cdata)
                        
                    if "initializeCharacter.spd" in req:
                        cmd, data = self.handle_charinit(cdata)
                        
                    if "getQWCData.spd" in req:
                        cmd, data = self.handle_qwcdata(cdata)
                        
                    if "getMultiPlayGrade.spd" in req:
                        cmd = 0x28
                        data = "0100000000000000000000000000000000000000000000000000000000".decode("hex")
                    
                    if "getBloodMessageGrade.spd" in req:
                        cmd = 0x29
                        data = "0100000000".decode("hex")
                        
                    if "getTimeMessage.spd" in req:
                        cmd = 0x22
                        data = "000000".decode("hex")
                    
                    if "getBloodMessage.spd" in req:
                        cmd = 0x1f
                        data = "00000000".decode("hex")
                        
                    if "addReplayData.spd" in req:
                        cmd = 0x1d
                        data = "01000000".decode("hex")
                        
                    if "getReplayList.spd" in req:
                        cmd, data = self.handle_getReplayList(cdata)
                    
                    if "getReplayData.spd" in req:
                        cmd, data = self.handle_getReplayData(cdata)
                    
                    if "getWanderingGhost.spd" in req:
                        cmd, data = self.handle_getWanderingGhost(cdata)
                        
                    if "setWanderingGhost.spd" in req:
                        cmd, data = self.handle_setWanderingGhost(cdata)
                        
                    if "getSosData.spd" in req:
                        cmd, data = self.handle_getSosData(cdata)
                        
                    if "addSosData.spd" in req:
                        cmd, data = self.handle_addSosData(cdata)
                        
                    if "checkSosData.spd" in req:
                        cmd, data = self.handle_checkSosData(cdata)
                        
                    if "outOfBlock.spd" in req:
                        cmd, data = self.handle_outOfBlock(cdata)
                        
                    if "summonOtherCharacter.spd" in req:
                        cmd, data = self.handle_summonOtherCharacter(cdata)
                        
                    if "initializeMultiPlay.spd" in req:
                        cmd, data = 0x15, "\x01"
                        
                    if data == None:
                        print repr(req)
                        print repr(cdata)
                        raise Exception("UNKNOWN CLIENT REQUEST")
                        
                    res = self.prepare_response(cmd, data)
                    # print "sending"
                    # print res
                    
                sc.sendall(res)
                sc.close()
                
            except KeyboardInterrupt:
                #sc.close()
                #gserver.close()
                raise
            except:
                #sc.close()
                traceback.print_exc()
            
            
    def handle_login(self, cdata):
        motd = "\x01\x01Hello from %x fake server!"
        #data = "\x01" + struct.pack(">I", len(motd) + 4) + motd + "\x00"
        data = motd + "\x00"
        
        #data = '\x01\xf3\x02\x00\x00\x01\x01Conclusion of Online Service for Lolll\xe2\x80\x99s Souls\r\n\r\nOnline service for Demon\xe2\x80\x99s Souls will conclude \r\non February 28, 2018. \r\nWe are very thankful for the countless players \r\nwho have enjoyed our title since its release back \r\nin 2010.\r\n\r\nEven after the online service concludes, \r\nyou will continue to be able to play the game offline. \r\nWe have listed the features that will cease functioning \r\nbelow.\r\n\r\nDemon\xe2\x80\x99s Souls Online Service Conclusion\r\nFebruary 28, 2018\r\n8:00 (UTC)\r\n\r\nFeatures That Will Cease: \r\nMultiplayer \r\n(cooperative, invading other worlds, challenge play)\r\nHint messages\r\nOther players\xe2\x80\x99 bloodstains\r\nWandering apparitions\r\nViewing rankings\r\n\r\nAgain, thank youto all players who have enjoyed \r\nDemon\xe2\x80\x99s Souls over the years\x00\x00'
        return 0x01, data
        
    def handle_charinit(self, cdata):
        params = get_params(cdata)
        charname = params["characterID"] + params["index"][0]
        
        data = charname + "\x00"
        return 0x17, data
        
    def handle_qwcdata(self, cdata):
        data = ""
        #testparams = (0x5e, 0x81, 0x70, 0x7e, 0x7a, 0x7b, 0x00)
        testparams = (0xff, -0xff, -0xffff, -0xffffff, -0x7fffffff, 0, 0)
        
        for i in xrange(7):
            data += struct.pack("<ii", testparams[i], 0)
            
        return 0x0e, data
        
    def handle_getWanderingGhost(self, cdata):
        params = get_params(cdata)
        print params
        blockID = params["blockID"]
        if blockID not in self.ghosts:
            data = struct.pack("<II", 0, 0)
        else:
            nghosts = min(len(self.ghosts[blockID]), 6)
                
            data = struct.pack("<II", 0, nghosts)
            for i in xrange(nghosts):
                replay = random.choice(self.ghosts[blockID])
                replay = base64.b64encode(replay).replace("+", " ")
                data += struct.pack("<I", len(replay))
                data += replay
    
        return 0x11, data
        
    def handle_setWanderingGhost(self, cdata):
        params = get_params(cdata)
        blockID = params["ghostBlockID"]
        
        # try:
            # replay = decode_broken_base64(params["replayData"])
            # z = zlib.decompressobj()
            # data = z.decompress(replay)
            # assert z.unconsumed_tail == ""
            
            # sio = cStringIO.StringIO(data)
            # poscount, num1, num2 = struct.unpack(">III", sio.read(12))
            # print "%08x %08x %08x" % (poscount, num1, num2)
            # for i in xrange(poscount):
                # posx, posy, posz, angx, angy, angz, num3, num4 = struct.unpack(">ffffffII", sio.read(32))
                # print "%7.2f %7.2f %7.2f %7.2f %7.2f %7.2f %08x %08x" % (posx, posy, posz, angx, angy, angz, num3, num4)
            # unknowns = struct.unpack(">iiiiiiiiiiiiiiiiiiii", sio.read(4 * 20))
            # print unknowns
            # playername = sio.read(24).decode("utf-16be").rstrip("\x00")
            # print repr(playername)
            
            # if blockID not in self.ghosts:
                # self.ghosts[blockID] = []
            # self.ghosts[blockID].append(replay)
        # except:
            # print "bad data", repr(params)
            # traceback.print_exc()
        
        return 0x17, "01".decode("hex")
    
    def handle_getReplayList(self, cdata):
        params = get_params(cdata)
        blockID = make_signed(int(params["blockID"]))
        replayNum = int(params["replayNum"])
        print blockID, replayNum
        
        data = struct.pack("<I", replayNum)
        for i in xrange(replayNum):
            header = random.choice(self.replayheaders[blockID])
            data += header.to_bin()
            
        return 0x1f, data
        
    def handle_getReplayData(self, cdata):
        params = get_params(cdata)
        ghostID = int(params["ghostID"])
        print ghostID
        
        ghostdata = self.replaydata[ghostID]
        data = struct.pack("<II", ghostID, len(ghostdata)) + ghostdata
            
        return 0x1e, data
        
    def handle_addSosData(self, cdata):
        params = get_params(cdata)
        sos = SOSData(params, self.SOSindex)
        self.SOSindex += 1
        
        if sos.characterID in self.playerSOS:
            print "removing old SOS"
            oldsos = self.playerSOS[sos.characterID]
            del self.activeSOS[oldsos.sosID]
            del self.playerSOS[oldsos.characterID]
            
        self.activeSOS[sos.sosID] = sos
        self.playerSOS[sos.characterID] = sos
        
        print "added SOS, current list", self.activeSOS, self.playerSOS
        return 0x0a, "\x01"
        
    def handle_getSosData(self, cdata):
        # blockID=20370&maxSosNum=10&Black=5&Invate=5&sosNum=0&sosList=&playerLevelMax=83&playerLevelMin=51&BlackMax=83&BlackMin=51&InvateMax=65&InvateMin=49&ver=100&
        params = get_params(cdata)
        blockID = int(params["blockID"])
        sosNum = int(params["sosNum"])
        sosList = params["sosList"].split("a0a")
        sos_known = []
        sos_new = []
        
        for sos in self.activeSOS.values():
            if sos.blockID == blockID:
                if str(sos.sosID) in sosList:
                    sos_known.append(struct.pack("<I", sos.sosID))
                    print "adding known SOS", sos.sosID
                else:
                    sos_new.append(sos.serialize())
                    print "adding new SOS", sos.sosID
    
        data =  struct.pack("<I", len(sos_known)) + "".join(sos_known)
        data += struct.pack("<I", len(sos_new)) + "".join(sos_new)
        print "sending", repr(data)
        
        return 0x0f, data

    def handle_checkSosData(self, cdata):
        params = get_params(cdata)
        characterID = params["characterID"]
        
        print characterID, self.playerPending
        if characterID in self.playerPending:
            print "GOT DATA, SENDING"
            data = self.playerPending[characterID]
            del self.playerPending[characterID]
        else:
            print "no data"
            data = "\x00"
                    
        return 0x0b, data
        
    def handle_outOfBlock(self, cdata):
        params = get_params(cdata)
        characterID = params["characterID"]
        if characterID in self.playerSOS:
            print "removing old SOS"
            oldsos = self.playerSOS[characterID]
            del self.activeSOS[oldsos.sosID]
            del self.playerSOS[oldsos.characterID]
            
        return 0x15, "\x01"
        
# 'POST /cgi-bin/summonOtherCharacter.spd HTTP/1.1'
# 'ghostID=1234564&NPRoomID=/////05YUlYFFQyAAAABAQAAAAAEgAAAAgEAAAAAAIAAAAYBAAAAAAAAAAAAAQAAACcVAAAAAQEAAABOJQAAAAIBAAAAdTUAAAADAQAAAJxFAAAABAEAAADDVQAAAAUBAAAA6m
# UAAAAGAQAAARF1AAAABwEAAAE4hQAAAAgEAAB5AG0AZwB2AGUAAAB5AG0AZwB2AGUAAAAQAAAAAAAAAAAAAQACAAB8/Q===??&ver=100&\x00'

    def handle_summonOtherCharacter(self, cdata):
        params = get_params(cdata)
        ghostID = int(params["ghostID"])
        print "ghostID", ghostID, self.activeSOS
        if ghostID in self.activeSOS:
            sos = self.activeSOS[ghostID]
            print "adding to", repr(sos.characterID)
            self.playerPending[sos.characterID] = params["NPRoomID"]
        
        return 0x0a, "\x01"
            
    
    def prepare_response(self, cmd, data):
        # The official servers were REALLY inconsistent with the data length field
        # I just set it to what seems to be the correct value and hope for the best,
        # has been working so far
        data = chr(cmd) + struct.pack("<I", len(data) + 5) + data
        
        # The newline at the end here is important for some reason
        # - standard responses won't work without it
        # - bootstrap response won't work WITH it
        return self.add_headers(base64.b64encode(data) + "\n")

    def prepare_response_bootstrap(self, data):
        return self.add_headers(base64.b64encode(data))
        
    def add_headers(self, data):
        res  = "HTTP/1.1 200 OK\r\n"
        res += "Date: " + strftime("%a, %d %b %Y %H:%M:%S GMT", gmtime()) + "\r\n"
        res += "Server: Apache\r\n"
        res += "Content-Length: %d\r\n" % len(data)
        res += "Connection: close\r\n"
        res += "Content-Type: text/html; charset=UTF-8\r\n"
        res += "\r\n"
        res += data
        return res
        
server = Server()
server.run()