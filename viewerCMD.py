import zlib
import struct
from pathlib import Path
import csv
from mysql import connector
import pymysql
import encodings.idna
from mysql.connector.locales.eng import client_error
import json
import pvfReader
from zhconv import convert
import hashlib
import pickle
import re
import time 
import threading
__version__ = 'uu5!^%jg'

print(f'物品栏装备删除工具_CMD {__version__}\n\n')
configPathStr = 'config/config.json'
pvfCachePathStr = 'config/pvf.cache'
magicSealDictPathStr = 'config/magicSealDict.json'
jobDictPathStr = 'config/jobDict.json'
csvPathStr = 'config/'
csvPath = Path(csvPathStr)
fcgPath = Path(configPathStr)
cachePath = Path(pvfCachePathStr)
magicDictPath = Path(magicSealDictPathStr)
jobPath = Path(jobDictPathStr)

PVF_CACHE_VERSION = '230223'
CONFIG_VERSION = '230224e'
PVFcacheDicts = {'_cacheVersion':PVF_CACHE_VERSION}

ITEMS_dict = {}
stackableDict = {}
equipmentDict = {}
equipmentDetailDict = {}    #根据种类保存的物品列表
equipmentForamted = {}  #格式化的装备字典
PVFcacheDict = {}
magicSealDict = {}
jobDict = {}

SQL_ENCODE_LIST = ['latin1','windows-1252','utf-8']
SQL_CONNECTOR_LIST = [pymysql,connector,]
SQL_CONNECTOR_IIMEOUT_KW_LIST = [
    {'connect_timeout':2},
    {'connection_timeout':2},

]
sqlEncodeUse = 0


config_template = {
        'DB_IP' : '192.168.200.131',
        'DB_PORT' : 3306,
        'DB_USER' : 'game',
        'DB_PWD' : '123456',
        'PVF_PATH': '',
        'TEST_ENABLE': 1,
        'TYPE_CHANGE_ENABLE':0,
        'CONFIG_VERSION':CONFIG_VERSION,
        'INFO':'台服DNF吧',
        'FONT':[['',17],['',17],['',20]],
        'VERSION':__version__,
        'TITLE':'背包编辑工具'
    }
config = {}
if fcgPath.exists():
    config = json.load(open(configPathStr,'r'))
if config.get('CONFIG_VERSION')!=CONFIG_VERSION:
    '''config版本错误'''
    config = config_template
    json.dump(config_template,open(configPathStr,'w'))
else:
    config['FONT'] = [[item[0],int(item[1])] for item in config['FONT']]
        
if jobPath.exists():
    jobDict = json.load(open(jobDictPathStr,'r'))
    jobDict_tmp = {}
    for key,value in jobDict.items():
        valueNew = {}
        for key1, value1 in value.items():
            valueNew[int(key1)] = convert(value1,'zh-cn').strip()
        jobDict_tmp[int(key)] = valueNew
    jobDict = jobDict_tmp
if magicDictPath.exists():
    magicSealDict = json.load(open(magicSealDictPathStr,'r'))
    magicSealDict_tmp = {}
    for key,value in magicSealDict.items():
        magicSealDict_tmp[int(key)] = value
    magicSealDict = magicSealDict_tmp



if cachePath.exists():
    try:
        with open(pvfCachePathStr,'rb') as pvfFile:
            cacheCompressed = pvfFile.read()
            PVFcacheDicts:dict = pickle.loads(zlib.decompress(cacheCompressed))
            if PVFcacheDicts.get('_cacheVersion') != PVF_CACHE_VERSION:
                PVFcacheDicts = {'_cacheVersion':PVF_CACHE_VERSION}
    except:
        pass

positionDict = {
    0x00:['快捷栏',[3,9]],
    0x01:['装备栏',[9,57]],
    0x02:['消耗品',[57,105]],
    0x03:['材料',[105,153]],
    0x04:['任务材料',[153,201]],
    0x05:['宠物',[98,99]],#正在使用的宠物
    0x06:['宠物装备',[0,49],[99,102]],#装备栏和正在使用的装备
    0x07:['宠物消耗品',[49,98]],
    0x0a:['副职业',[201,249]]
}

class DnfItemSlot():
    '''物品格子对象，存储格子信息'''
    typeDict ={
        0x00:'已删除/空槽位',
        0x01:'装备',
        0x02:'消耗品',
        0x03:'材料',
        0x04:'任务材料',
        0x05:'宠物',
        0x06:'宠物装备',
        0x07:'宠物消耗品',
        0x0a:'副职业'
    }
    increaseTypeDict = {
        0x00:'空-0',
        0x01:'异次元体力-1',
        0x02:'异次元精神-2',
        0x03:'异次元力量-3',
        0x04:'异次元智力-4'
    }
    def __init__(self,item_bytes:bytes) -> None:
        if len(item_bytes)<61:
            item_bytes = b'\x00'*61
        self.oriBytes = item_bytes
        self.isSeal = item_bytes[0]
        self.type = item_bytes[1]
        self.id = struct.unpack('I',item_bytes[2:6])[0]
        self.enhancementLevel = item_bytes[6]
        if self.typeZh == '装备':
            self.num_grade = struct.unpack('!I',item_bytes[7:11])[0]
        else:
            self.num_grade = struct.unpack('I',item_bytes[7:11])[0]
        self.durability = struct.unpack('H',item_bytes[11:13])[0]
        self.orb_bytes = item_bytes[13:17]
        self.increaseType = item_bytes[17]
        self.increaseValue = struct.unpack('H',item_bytes[18:20])[0]
        self._others20_30 = item_bytes[20:31]
        self.otherworld = item_bytes[31:33]#struct.unpack('H',item_bytes[31:33])[0]
        self._others32_36 = item_bytes[33:37]
        self.magicSeal = item_bytes[37:51]
        self.coverMagic = self.magicSeal[-1]   #表示被替换的魔法封印，当第四属性存在的时候有效

        self.forgeLevel = item_bytes[51]
        self._others = item_bytes[52:]
    
    def readMagicSeal(self):
        def read3Bytes(seal:bytes=b'\x00\x00\x00'):
            sealID = seal[0]
            sealType = magicSealDict.get(sealID)
            if sealType is None: sealType = ''
            sealLevel = int.from_bytes(seal[1:],'big')
            return sealID,sealType.strip(), sealLevel  #ID，type，level
        seal_1 = read3Bytes(self.magicSeal[:3])
        seal_2 = read3Bytes(self.magicSeal[3:6])
        seal_3 = read3Bytes(self.magicSeal[6:9])
        seal_4 = read3Bytes(self.magicSeal[10:13])
        return [self.coverMagic,[seal_1,seal_2,seal_3,seal_4]]
    
    def buildMagicSeal(self,sealTuple:tuple=(0,[[1,'name',1]*4])):
        coverMagic,seals = sealTuple
        magicSeal = b''
        for i in range(3):
            sealID, sealType, sealLevel = seals[i]
            if sealID==0:
                magicSeal += b'\x00\x00\x00'
                continue
            magicSeal += sealID.to_bytes(1,'big')
            magicSeal += sealLevel.to_bytes(2,'big')
        magicSeal += self.magicSeal[9:10]
        sealID, sealType, sealLevel = seals[3]
        if sealID==0:
            magicSeal += b'\x00\x00\x00'
        else:
            magicSeal += sealID.to_bytes(1,'big')
            magicSeal += sealLevel.to_bytes(2,'big')
        magicSeal += coverMagic.to_bytes(1,'big')
        return magicSeal
        #self.magicSeal = magicSeal


    @property
    def typeZh(self):
        return self.typeDict.get(self.type)
    
    @property
    def increaseTypeZh(self):
        return self.increaseTypeDict.get(self.increaseType)

    def build_bytes(self):
        item_bytes = b''
        item_bytes += struct.pack('B',self.isSeal)
        item_bytes += struct.pack('B',self.type)
        item_bytes += struct.pack('I',self.id)
        item_bytes += struct.pack('B',self.enhancementLevel)
        #print(self.num_grade)
        if self.typeZh == '装备':
            item_bytes += struct.pack('!I',self.num_grade)
        else:
            item_bytes += struct.pack('I',self.num_grade)
        item_bytes += struct.pack('H',self.durability)
        item_bytes += self.orb_bytes
        item_bytes += struct.pack('B',self.increaseType)
        item_bytes += struct.pack('H',self.increaseValue)
        item_bytes += self._others20_30
        item_bytes += self.otherworld#struct.pack('H',self.otherworld)
        item_bytes += self._others32_36
        item_bytes += self.magicSeal
        item_bytes += struct.pack('B',self.forgeLevel)
        item_bytes += self._others
        return item_bytes


    def __repr__(self) -> str:
        s = f'[{self.typeDict.get(self.type)}]{ITEMS_dict.get(self.id)} '
        if self.typeDict.get(self.type) in ['消耗品','材料','任务材料','副职业','宠物','宠物消耗品']:
            s += f'数量:{self.num_grade}'
        elif self.typeDict.get(self.type) in ['装备']:
            if self.isSeal!=0:
                s+=f'[封装]'
            if self.enhancementLevel>0:
                s+=f' 强化:+{self.enhancementLevel}'
            s += f' 耐久:{self.durability}'
            if self.increaseType!=0:
                s += f' 增幅:{self.increaseTypeZh}+{self.increaseValue}'#self.increaseTypeDict.get(self.increaseType)
            if  self.forgeLevel>0:
                s += f' 锻造:+{self.forgeLevel}'
        return s
    __str__ = __repr__



def __unpackBlob_skill(fbytes):
    items_bytes = zlib.decompress(fbytes[4:])
    num = len(items_bytes)//2
    result = []
    for i in range(num):
        skillID,skilllevel = struct.unpack('BB',items_bytes[i*2:(i+1)*2])
        result.append([skillID,skilllevel])
    return result


def unpackBLOB_Item(fbytes):
    '''返回[index, DnfItemGrid对象]'''
    items_bytes = zlib.decompress(fbytes[4:])
    num = len(items_bytes)//61
    result = []
    for i in range(num):
        #if items_bytes[i*61:(i+1)*61] == b'\x00'*61:continue
        item = DnfItemSlot(items_bytes[i*61:(i+1)*61])
        result.append([i, item])
    return result

def buildDeletedBlob2(deleteList,originBlob):
    '''返回删除物品后的数据库blob字段'''
    prefix = originBlob[:4]
    items_bytes = bytearray(zlib.decompress(originBlob[4:]))
    for i in deleteList:
        items_bytes[i*61:i*61+61] = bytearray(b'\x00'*61)
    blob = prefix + zlib.compress(items_bytes)
    return blob

def buildBlob(originBlob,editedDnfItemGridList):
    '''传入原始blob字段和需要修改的位置列表[ [1, DnfItemGrid对象], ... ]'''
    prefix = originBlob[:4]
    items_bytes = bytearray(zlib.decompress(originBlob[4:]))
    for i,itemGird in editedDnfItemGridList:
        items_bytes[i*61:i*61+61] = itemGird.build_bytes()
    blob = prefix + zlib.compress(items_bytes)
    return blob



def getItemInfo(itemID:int):
    if PVFcacheDict.get('stringtable') is not None:
        stringtable = PVFcacheDict['stringtable']
        nString = PVFcacheDict['nstring']
        idPathContentDict = PVFcacheDict['idPathContentDict']
        #try:
        res = pvfReader.TinyPVF.content2List(idPathContentDict[itemID],stringtable,nString)
        #except:
        #    res = '',['无此id记录']
    else:
        res =  'type',['']
    return res

def equipmentDetailDict_transform():
    global equipmentForamted
    keyMap = {
        '短剑':'ssword','太刀':'katana','巨剑':'hsword','钝器':'club','光剑':'beamsword',
        '手套':'knuckle','臂铠':'gauntlet','爪':'claw','拳套':'boxglove','东方棍':'tonfa',
        '自动手枪':'automatic','手弩':'bowgun','左轮':'revolver','步枪':'musket','手炮':'hcannon',
        '法杖':'staff','魔杖':'rod','棍棒':'pole','矛':'spear','扫把':'broom',
        '十字架':'cross','镰刀':'scythe','念珠':'rosary','图腾':'totem','战斧':'axe',
        '手杖':'wand','匕首':'dagger','双剑':'twinsword','项链':'amulet','手镯':'wrist',
        '戒指':'ring','辅助装备':'support','魔法石':'magicstone','称号':'title',
        '上衣':'jacket','头肩':'shoulder','下装':'pants','腰带':'belt','鞋':'shoes',
        '布甲':'cloth','皮甲':'leather','轻甲':'larmor','重甲':'harmor','板甲':'plate',
        '鬼剑士':'swordman','格斗家':'fighter','神枪手':'gunner','魔法师':'mage','圣职者':'priest',
        '暗夜使者':'thief'
    }
    keyMapTMP = {}
    for key,value in keyMap.items():
        keyMapTMP[value] =key
    keyMap.update(keyMapTMP)
    equipmentForamted = {
        '武器':{
            '鬼剑士':{'短剑':{},'太刀':{},'巨剑':{},'钝器':{},'光剑':{}},
            '格斗家':{'手套':{},'臂铠':{},'爪':{},'拳套':{},'东方棍':{}},
            '神枪手':{'自动手枪':{},'手弩':{},'左轮':{},'步枪':{},'手炮':{}},
            '魔法师':{'法杖':{},'魔杖':{},'棍棒':{},'矛':{},'扫把':{}},
            '圣职者':{'十字架':{},'镰刀':{},'念珠':{},'图腾':{},'战斧':{}},
            '暗夜使者':{'手杖':{},'匕首':{},'双剑':{}}
        },
        '防具':{
            '布甲':{'上衣':{},'头肩':{},'下装':{},'腰带':{},'鞋':{}},
            '皮甲':{'上衣':{},'头肩':{},'下装':{},'腰带':{},'鞋':{}},
            '轻甲':{'上衣':{},'头肩':{},'下装':{},'腰带':{},'鞋':{}},
            '重甲':{'上衣':{},'头肩':{},'下装':{},'腰带':{},'鞋':{}},
            '板甲':{'上衣':{},'头肩':{},'下装':{},'腰带':{},'鞋':{}}
        },
        '首饰':{
            '项链':{},
            '手镯':{},
            '戒指':{}
        },
        '特殊装备':{
            '辅助装备':{},
            '魔法石':{},
            '称号':{},
            '其它':{}
        }
    }
    i=0
    def add_dict_all(outDict:dict,inDict:dict):
        nonlocal i
        if isinstance(inDict,dict):
            for key,value in inDict.items():
                if isinstance(value,str):
                    outDict[key] = convert(value.strip(),'zh-cn')
                    i+=1
                else:
                    add_dict_all(outDict,value)

    for dirName,dirDict in PVFcacheDict['equipmentStructuredDict'].items():
        if dirName not in ['character','creature','monster']:
            add_dict_all(equipmentForamted['特殊装备']['其它'],dirDict)
    
    for dir1Name, dir2Dict in PVFcacheDict['equipmentStructuredDict']['character'].items():
        if dir1Name == 'common':#处理防具和首饰
            for commonType, partDir in dir2Dict.items():
                if not isinstance(partDir,dict):
                    if isinstance(partDir,str):
                        id_, name = commonType, partDir
                        equipmentForamted['特殊装备']['其它'][id_] = convert(name.strip(),'zh-cn')
                    continue
                if commonType in ['amulet','wrist','ring']:#首饰
                    add_dict_all(equipmentForamted['首饰'][keyMap[commonType]],partDir)
                elif commonType in ['magicstone','title','support']:    #特殊装备
                    add_dict_all(equipmentForamted['特殊装备'][keyMap[commonType]],partDir)
                else:   #是防具
                    for armorType,itemDict in partDir.items():
                        if not isinstance(itemDict,dict): 
                            if isinstance(itemDict,str):
                                id_, name = armorType,itemDict
                                equipmentForamted['特殊装备']['其它'][id_] = convert(name.strip(),'zh-cn')
                            continue
                        add_dict_all(equipmentForamted['防具'][keyMap[armorType]][keyMap[commonType]],partDir)

        else:   #处理武器
            jobName = dir1Name
            if jobName not in keyMap.keys():    #扩充不存在的角色
                keyMap[jobName] = jobName
                equipmentForamted['武器'][jobName] = {}
            jobDirsDict = dir2Dict
            for weaponDirName, weaponTypeDict in jobDirsDict.items():
                if not isinstance(jobDirsDict,dict):continue
                if weaponDirName=='weapon':
                    for weaponType, weaponDict in weaponTypeDict.items():
                        if not isinstance(weaponDict,dict): 
                            if isinstance(weaponDict,str):
                                id_, name = weaponType, weaponDict
                                equipmentForamted['特殊装备']['其它'][id_] = convert(name.strip(),'zh-cn')
                            continue
                        if weaponType not in keyMap.keys(): #扩充不存在的武器名
                            keyMap[weaponType] = weaponType
                            equipmentForamted['武器'][keyMap[jobName]][weaponType] = {}
                        add_dict_all(equipmentForamted['武器'][keyMap[jobName]][keyMap[weaponType]],weaponDict)
                else:
                    equipmentForamted['武器'][keyMap[jobName]]['其它'] = {}
                    add_dict_all(equipmentForamted['武器'][keyMap[jobName]]['其它'],weaponTypeDict)

    print(f'装备查询转换完成,{i}件装备')
    return equipmentForamted
                        
def loadItems2(usePVF=False,pvfPath='',showFunc=lambda x:print(x),MD5='0'):        
    global ITEMS_dict,  PVFcacheDict, magicSealDict, jobDict, equipmentDict
    ITEMS = []
    ITEMS_dict = {}
    jobDict = {}
    magicSealDict = {}
    if pvfPath=='':
        pvfPath = config['PVF_PATH']
    if usePVF :
        p = Path(pvfPath)
        if  MD5 in PVFcacheDicts.keys():
            if PVFcacheDicts.get(MD5) is not None:
                #PVFcacheDict_tmp = PVFcacheDicts.get(MD5)
                #if isinstance(PVFcacheDict_tmp,dict):
                PVFcacheDict = PVFcacheDicts.get(MD5)
                info = f'加载pvf缓存完成'
                config['PVF_PATH'] = MD5
                #else:
                #    info = f'PVF缓存读取错误'
                #    return info
                
        elif  '.pvf' in pvfPath and p.exists():
            MD5 = hashlib.md5(open(pvfPath,'rb').read()).hexdigest().upper()
            if MD5 in PVFcacheDicts.keys():
                PVFcacheDict = PVFcacheDicts.get(MD5)
                info = f'加载pvf缓存完成' 
            else:
                pvf = pvfReader.FileTree(pvfHeader=pvfReader.PVFHeader(pvfPath))
                print('加载PVF中...\n',pvf.pvfHeader)
                pvf.loadLeafs(['stackable','equipment'])
                print('PVF加载：',pvf._fileNum)
                showFunc(f'PVF加载文件数...{pvf._fileNum}')
                all_items_dict = pvfReader.get_Item_Dict(pvf)
                PVFcacheDict = {}
                PVFcacheDict['stringtable'] = pvf.stringtable
                PVFcacheDict['nstring'] = pvf.nStringTableLite
                PVFcacheDict['idPathContentDict'] = all_items_dict.pop('idPathContentDict')
                PVFcacheDict['magicSealDict'] = all_items_dict.pop('magicSealDict')
                PVFcacheDict['jobDict'] = all_items_dict.pop('jobDict')
                PVFcacheDict['equipment'] = all_items_dict.pop('equipment')
                PVFcacheDict['stackable'] = all_items_dict.pop('stackable')
                PVFcacheDict['equipmentStructuredDict'] = all_items_dict.pop('equipmentStructuredDict')
                
                
                info = f'加载pvf文件完成'
                PVFcacheDicts[MD5] = PVFcacheDict
                pvfFile = open(pvfCachePathStr,'wb')
                cacheCompressed = zlib.compress(pickle.dumps(PVFcacheDicts))
                pvfFile.write(cacheCompressed)
                pvfFile.close()
                print(f'pvf cache saved. {PVFcacheDict.keys()}')                
            config['PVF_PATH'] = MD5
        else:
            info = 'PVF文件路径错误'
            return info
        ITEMS_dict = {}
        ITEMS_dict.update(PVFcacheDict['stackable'])
        ITEMS_dict.update(PVFcacheDict['equipment'])
        magicSealDict = PVFcacheDict['magicSealDict']
        jobDict = PVFcacheDict['jobDict']
        equipmentDict = PVFcacheDict['equipment']
        equipmentDetailDict_transform() #转换为便于索引的格式
        info += f' 物品：{len(PVFcacheDict["stackable"].keys())}条，装备{len(PVFcacheDict["equipment"])}条'
    else:
        csvList = list(filter(lambda item:item.name[-4:].lower()=='.csv',[item for item in csvPath.iterdir()]))
        print(f'物品文件列表:',csvList)
        for fcsv in csvList:
            csv_reader = list(csv.reader(open(fcsv,encoding='utf-8',errors='ignore')))[1:]
            ITEMS.extend(csv_reader)
        for item in ITEMS:
            if len(item)!=2:
                print(item)
            else:
                ITEMS_dict[int(item[1])] = item[0]
        magicSealDict = json.load(open(magicSealDictPathStr,'r'))
        jobDict = json.load(open(jobDictPathStr,'r'))
        info = f'加载csv文件获得{len(ITEMS)}条物品信息记录，魔法封印{len(magicSealDict.keys())}条'

    for key,value in ITEMS_dict.items():
        try:
            ITEMS_dict[key] = convert(value,'zh-cn').strip()
        except:
            ITEMS_dict[key] = value
    magicSealDict_tmp = {}
    for key,value in magicSealDict.items():
        magicSealDict_tmp[int(key)] = value
    magicSealDict = magicSealDict_tmp
    jobDict_tmp = {}
    for key,value in jobDict.items():
        valueNew = {}
        for key1, value1 in value.items():
            valueNew[int(key1)] = convert(value1,'zh-cn').strip()
        jobDict_tmp[int(key)] = valueNew
    jobDict = jobDict_tmp
    for key,value in equipmentDict.items():
        equipmentDict[key] = convert(value,'zh-cn')

    json.dump(config,open(configPathStr,'w'),ensure_ascii=False)
    return info

def getUID(username=''):
    sql = f"select UID from accounts where accountname='{username}';"
    account_cursor.execute(sql)
    res = account_cursor.fetchall()
    if len(res)==0:
        print('未查询到记录')
        return None
    return res[0][0]

def getCharactorInfo(name='',uid=0):
    '''返回 编号，角色名，等级，职业，成长类型，删除状态'''
    global sqlEncodeUse
    if uid!=0:
        sql = f"select charac_no, charac_name, lev, job, grow_type, delete_flag from charac_info where m_id='{uid}';"
        charactor_cuesor.execute(sql)
        res = charactor_cuesor.fetchall()
    else:
        name_new = name.encode('utf-8').decode(SQL_ENCODE_LIST[sqlEncodeUse])
        sql = f"select charac_no, charac_name, lev, job, grow_type, delete_flag  from charac_info where charac_name='{name_new}';"
        charactor_cuesor.execute(sql)
        res = charactor_cuesor.fetchall()
        name_tw = convert(name,'zh-tw')
        if name!=name_tw:
            name_tw_new = name_tw.encode('utf-8').decode(SQL_ENCODE_LIST[sqlEncodeUse])
            sql = f"select charac_no, charac_name, lev, job, grow_type, delete_flag from charac_info where charac_name='{name_tw_new}';"
            charactor_cuesor.execute(sql)
            res.extend(charactor_cuesor.fetchall())
    res_new = []
    for i in res:
        record = list(i)
        #record[1] = convert(record[1].encode('windows-1252').decode('utf-8'),'zh-cn')
        while sqlEncodeUse < len(SQL_ENCODE_LIST):
            try:
                record[1] = convert(record[1].encode(SQL_ENCODE_LIST[sqlEncodeUse]).decode('utf-8'),'zh-cn')
                break
            except:
                sqlEncodeUse += 1
                print(f'{SQL_ENCODE_LIST[sqlEncodeUse-1]}编码解码失败，切换连接编码为{SQL_ENCODE_LIST[sqlEncodeUse]}')
        res_new.append(record)
    print(f'角色列表加载完成')
    return res_new

def getCharactorNo(name):
    name_new = name.encode('utf-8').decode(SQL_ENCODE_LIST[sqlEncodeUse])
    sql = f"select charac_no from charac_info where charac_name='{name_new}';"
    charactor_cuesor.execute(sql)
    res = charactor_cuesor.fetchall()

    name_tw = convert(name,'zh-tw')
    if name!=name_tw:
        name_tw_new = name_tw.encode('utf-8').decode(SQL_ENCODE_LIST[sqlEncodeUse])
        sql = f"select charac_no from charac_info where charac_name='{name_tw_new}';"
        charactor_cuesor.execute(sql)
        res.extend(charactor_cuesor.fetchall())
    return res

def getCargoAll(name='',cNo=0):
    '''获取仓库的blob字段'''
    if cNo==0:
        cNo = getCharactorNo(name)[0][0]
    get_all_sql = f'select cargo,jewel,expand_equipslot from charac_inven_expand where charac_no={cNo};'
    inventry_cursor.execute(get_all_sql)
    results = inventry_cursor.fetchall()
    return results

def getInventoryAll(name='',cNo=0):
    '''获取背包，穿戴槽，宠物栏的blob字段'''
    if cNo!=0:
        charac_no = cNo
    else:
        charac_no = getCharactorNo(name)[0][0]
    get_all_sql = f'select inventory,equipslot,creature from inventory where charac_no={charac_no};'
    inventry_cursor.execute(get_all_sql)
    results = inventry_cursor.fetchall()
    return results

def getAvatar(cNo):
    getAvatarSql = f'select ui_id,it_id,ability_no from user_items where charac_no={cNo};'
    inventry_cursor.execute(getAvatarSql)
    results = inventry_cursor.fetchall()
    res = []
    for ui_id,it_id,ability_no in results:
        res.append([ui_id,ITEMS_dict.get(it_id),it_id])
    return res

def getCreatureItem(name='',cNo=0):
    '''获取宠物'''
    if cNo!=0:
        charac_no = cNo
    else:
        charac_no = getCharactorNo(name)[0][0]
    get_creatures_sql = f'select ui_id,it_id,name from creature_items where charac_no={charac_no};'
    inventry_cursor.execute(get_creatures_sql)
    results = inventry_cursor.fetchall()
    #print(results)
    res = []
    for ui_id, it_id, name in results:
        name_new = name.encode('windows-1252',errors='ignore').decode(errors='ignore')
        res.append([ui_id,ITEMS_dict.get(it_id),it_id,name_new])
    return res

def setInventory(InventoryBlob,cNo,key='inventory'):
    if key in ['inventory','equipslot', 'creature']: table = 'inventory'
    if key in ['cargo','jewel','expand_equipslot']: table = 'charac_inven_expand'
    if key in ['skill_slot']:table = 'skill'
    sql_update = f'''update {table} set {key}=%s where charac_no={cNo};'''
    print(sql_update % InventoryBlob)
    try:
        inventry_cursor.execute(sql_update,(InventoryBlob,))
        inventry_db.commit()
        return True
    except:
        return False

def commit_change_blob(originBlob,editDict:dict,cNo,key):
    '''传入原始blob和修改的物品槽对象列表'''
    editList = list(editDict.items())
    blob_new = buildBlob(originBlob,editList)
    print(f'ID:{cNo}, {key}\n',unpackBLOB_Item(blob_new))
    return setInventory(blob_new,cNo,key)

def delCreatureItem(ui_id):
    try:
        sql = f'delete from creature_items where ui_id={ui_id};'
        print(sql)
        inventry_cursor.execute(sql)
        inventry_db.commit()
        return True
    except:
        return False
    
def delNoneBlobItem(ui_id,tableName='creature_items'):
    try:
        sql = f'delete from {tableName} where ui_id={ui_id};'
        print(sql)
        inventry_cursor.execute(sql)
        inventry_db.commit()
        return True
    except:
        return False

def enable_Hidden_Item(ui_id,tableName='user_items'):
    try:
        sql = f'update {tableName} set hidden_option=1 where ui_id={ui_id}'
        print(sql)
        inventry_cursor.execute(sql)
        inventry_db.commit()
        return True
    except:
        return False

def set_charac_info(cNo,*args,**kw):
    #print('set_characinfo',cNo,kw)
    for key,value in kw.items():
        if key=='charac_name':
            value = convert(value,'zh-tw').encode('utf-8').decode(SQL_ENCODE_LIST[sqlEncodeUse])
        sql = f'update charac_info set {key}=%s where charac_no={cNo}'
        print(sql)
        charactor_cuesor.execute(sql,(value,))
        charactor_db.commit()

def connect(infoFunc=lambda x:...): #多线程连接
    global account_db,account_cursor,inventry_db,inventry_cursor,charactor_db,charactor_cuesor
    connectorAvailuableList = []    #存储连接成功的数据库游标
    connectorTestedNum = 0  #完成连接测试的数量
    def innerThread(i,connector_used):
        nonlocal connectorAvailuableList, connectorTestedNum
        try:
            account_db = connector_used.connect(user=config['DB_USER'], password=config['DB_PWD'], host=config['DB_IP'], port=config['DB_PORT'], database='d_taiwan',**SQL_CONNECTOR_IIMEOUT_KW_LIST[i])
            account_cursor = account_db.cursor()
            inventry_db = connector_used.connect(user=config['DB_USER'], password=config['DB_PWD'], host=config['DB_IP'], port=config['DB_PORT'], database='taiwan_cain_2nd')
            inventry_cursor = inventry_db.cursor()
            charactor_db = connector_used.connect(user=config['DB_USER'], password=config['DB_PWD'], host=config['DB_IP'], port=config['DB_PORT'], database='taiwan_cain')#,charset='latin1'
            charactor_cuesor = charactor_db.cursor()
            connectorAvailuableList.append([account_db,account_cursor,inventry_db,inventry_cursor,charactor_db,charactor_cuesor])
            
        except Exception as e:
            infoFunc(str(e))
            print(f'连接失败，{str(connector_used)}, {e}')
        finally:
            connectorTestedNum += 1
    for i,connector_used in enumerate(SQL_CONNECTOR_LIST):
        t = threading.Thread(target=innerThread,args=(i,connector_used,))
        t.setDaemon(True)
        t.start()
    while connectorTestedNum<len(SQL_CONNECTOR_LIST):
        time.sleep(1)
    if len(connectorAvailuableList)==0:
        print('所有连接器连接失败，详情查看日志')
        return '所有连接器连接失败，详情查看日志'
    else:
        account_db,account_cursor,inventry_db,inventry_cursor,charactor_db,charactor_cuesor = connectorAvailuableList[0]
        json.dump(config,open(configPathStr,'w'),ensure_ascii=False)
        print(f'数据库连接成功({len(connectorAvailuableList)})')
        return f'数据库连接成功({len(connectorAvailuableList)})'
def connect1(infoFunc=lambda x:...):
    global account_db,account_cursor,inventry_db,inventry_cursor,charactor_db,charactor_cuesor
    connectorAvailuableList = []
    for i,connector_used in enumerate(SQL_CONNECTOR_LIST):
        try:
            account_db = connector_used.connect(user=config['DB_USER'], password=config['DB_PWD'], host=config['DB_IP'], port=config['DB_PORT'], database='d_taiwan',**SQL_CONNECTOR_IIMEOUT_KW_LIST[i])
            account_cursor = account_db.cursor()
            infoFunc('账号表连接成功')
            inventry_db = connector_used.connect(user=config['DB_USER'], password=config['DB_PWD'], host=config['DB_IP'], port=config['DB_PORT'], database='taiwan_cain_2nd')
            inventry_cursor = inventry_db.cursor()
            infoFunc('背包表连接成功')
            charactor_db = connector_used.connect(user=config['DB_USER'], password=config['DB_PWD'], host=config['DB_IP'], port=config['DB_PORT'], database='taiwan_cain')#,charset='latin1'
            charactor_cuesor = charactor_db.cursor()
            infoFunc('角色表连接成功')
            json.dump(config,open(configPathStr,'w'),ensure_ascii=False)
            print(f'连接成功{connector_used}')
            return True
        except Exception as e:
            account_cursor = None
            inventry_cursor = None
            charactor_cuesor = None
            infoFunc(str(e))
            if i+1<len(SQL_CONNECTOR_LIST):
                print(f'连接失败，{str(connector_used)}, {e}')
    print('所有连接器连接失败，详情查看日志')
    return '所有连接器连接失败，详情查看日志'

def searchItem(key,itemDict=None):
    if itemDict is None:
        itemDict = ITEMS_dict.items()
    res = []
    pattern = '.*?'.join(key)
    regex = re.compile(pattern)
    for id_,name in itemDict:
        try:
            match = regex.search(name)
            if match:
                res.append([id_,name])
        except:
            pass
    
    return sorted(res,key=lambda x:len(x[1]))

def searchMagicSeal(key):
    res = []
    pattern = '.*?'.join(key)
    regex = re.compile(pattern)
    for id_,name in magicSealDict.items():
        try:
            match = regex.search(name)
            if match:
                res.append([id_,name])
        except:
            pass
    
    return sorted(res,key=lambda x:len(x[1]))

def _test_selectDeleteInventry(cNo):
    while True:
        sel = input('====\n选择以下内容进行处理：\n【1】物品栏 Inventory\n【2】装备栏 Equipslot\n【3】宠物栏 Creature\n【4】宠物 Creature_items\n【5】仓库 Cargo\n【0】返回上一级\n>>>')
        inventory, equipslot, creature = getInventoryAll(cNo=cNo)[0]
        cargo,jewel,expand_equipslot = getCargoAll(cNo=cNo)[0]
        creature_items = getCreatureItem(cNo=cNo)
        if sel=='1': selected_blob = inventory;key = 'inventory'
        elif sel=='2':selected_blob = equipslot;key = 'equipslot'
        elif sel=='3':selected_blob = creature; key = 'creature'
        elif sel=='4':...
        elif sel=='5':selected_blob = cargo; key = 'cargo'
        elif sel=='0':return True
        else: continue
    
        while sel in ['1','2','3','5']:
            items = unpackBLOB_Item(selected_blob)
            print(f'====\n该角色{key}物品信息({len(items)})：\n位置编号，物品名，物品ID')
            for item in items:
                print(item)
            print('输入需要删除的物品编号，输入非数字时结束输入：')
            dels = []
            while True:
                try:
                    dels.append(int(input('>>>')))
                except:
                    break
            print('结束输入，当前待删除列表为：')
            for item in items:
                if item[0] in dels:
                    print(item)
                else:
                    continue
        
            delcmd = input('输入选项：\n【1】确定删除\n【2】重新设置删除列表\n【0】返回上一级\n>>>')
            if delcmd=='1':
                items_bytes = zlib.decompress(selected_blob[4:])
                #InventoryBlob_new = buildDeletedBlob(dels,items_bytes,selected_blob[:4])
                #print(InventoryBlob_new)
                InventoryBlob_new = buildDeletedBlob2(dels,selected_blob)
                if setInventory(InventoryBlob_new,cNo,key):
                    print('====删除成功====\n')
                else:
                    print('====删除失败，请检查数据库连接状况====\n')
                break
            elif delcmd=='2':
                continue
            elif delcmd=='0':
                break
    
        while sel in ['4']:
            items = creature_items
            print(f'====\n该角色宠物信息({len(items)})：\n宠物编号，宠物名，宠物ID，宠物昵称')
            for item in items:
                print(item)
            print('输入需要删除的宠物编号，输入非数字时结束输入：')
            dels = []
            while True:
                try:
                    dels.append(int(input('>>>')))
                except:
                    break
            print('结束输入，当前待删除列表为：')
            dels_fix = []
            for item in items:
                if item[0] in dels:
                    print(item)
                    dels_fix.append(item[0])
                else:
                    continue
        
            delcmd = input('输入选项：\n【1】确定删除\n【2】重新设置删除列表\n【0】返回上一级\n>>>')
            if delcmd=='1':
                for ui_id in dels_fix:
                    if delNoneBlobItem(ui_id,tableName='creature_items'):
                        print('====删除成功====\n')
                    else:
                        print('====删除失败====\n')
                break
            elif delcmd=='2':
                continue
            elif delcmd=='0':
                break
if __name__=='__main__':
    if not connect():
        input('数据库连接失败，请重新配置config.json文件')
        exit()
    loadItems2(True)
    print(f'数据库{config["DB_IP"]}:{config["DB_PORT"]}已连接')
    while True:
        cmd = input('====\n输入查询方式：\n【1】账户ID\n【2】角色名\n【0】退出\n>>>')
        if cmd=='1':
            account = input('====\n输入查询的账号名：')
            print('账户UID:',getUID(account))
            cInfos = getCharactorInfo(uid=getUID(account))
            while len(cInfos)>0:
                print(f'账户{account}拥有角色：\n全局编号，角色名，等级')
                valid_cNos = [item[0] for item in cInfos]
                for i in range(len(cInfos)):
                    print(cInfos[i])
                cNo = input('====\n输入查询角色的全局编号，输入【0】返回上一级：\n>>>')
                if cNo=='0':
                    break
                try:
                    cNo = int(cNo)
                except:
                    continue
                if cNo not in valid_cNos:
                    print('输入的角色编号错误')
                    continue
                _test_selectDeleteInventry(cNo)
        elif cmd=='2':
            while True:
                cName = input('====\n输入查询的角色名，直接输入回车返回上级：\n>>>')
                if cName=='':break
                cInfos = getCharactorInfo(cName)
                if len(cInfos)==0:
                    print('角色查询失败')
                    continue
                cInfo = cInfos[0]
                cNo = cInfo[0]
                print('全局编号，角色名，等级\n',cInfo)
                _test_selectDeleteInventry(cNo)
        elif cmd=='0':
            break
    #os.kill(subPid,signal.SIGINT)

