"""Install pinned, verified local parser tools; never run during a request."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import httpx

ROOT=Path(__file__).resolve().parent.parent
TIKA_VERSION='4.2.0'
TIKA_URL=f'https://downloads.apache.org/tika/{TIKA_VERSION}/tika-app-{TIKA_VERSION}.zip'
TIKA_SHA512='a9966e238fc0178a4ba3e7dd870c7b59894a16ec7759fc5582d62d0ecf9006b84e8ec97270ec2c3c0171acd57ef6ed351d55fa6884a4e52f2635fd148652bf0f'
JAVA_URL='https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.13%2B9/OpenJDK21U-jre_x64_windows_hotspot_21.0.13_9.zip'
JAVA_SHA256='2332c0b4cff6bed722da3567c91d5e47568bcba863fa4945d0a8d6fc76158628'


def download(url,path,algorithm,expected):
    if path.exists() and hashlib.new(algorithm,path.read_bytes()).hexdigest()==expected:return
    temporary=path.with_suffix('.part')
    digest=hashlib.new(algorithm);size=0
    with httpx.stream('GET',url,follow_redirects=True,timeout=60)as response,temporary.open('wb')as output:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            size+=len(chunk)
            if size>90*1024*1024:raise ValueError('Parser distribution exceeds the pinned download budget')
            output.write(chunk);digest.update(chunk)
    if digest.hexdigest()!=expected:raise ValueError('Parser distribution checksum mismatch; not installed')
    temporary.replace(path)


def unpack(archive,destination):
    destination=destination.resolve();destination.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive)as package:
        entries=package.infolist()
        if len(entries)>5000 or sum(item.file_size for item in entries)>400*1024*1024:
            raise ValueError('Parser distribution exceeds the extraction budget')
        for item in entries:
            target=(destination/item.filename).resolve()
            if not target.is_relative_to(destination) or (item.external_attr>>16)&0o170000==0o120000:
                raise ValueError('Unsafe parser distribution path')
        package.extractall(destination)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination',type=Path,default=ROOT/'data/vendor')
    parser.add_argument('--with-java',action='store_true',help='Install the pinned portable Windows x64 JRE without changing system settings')
    args=parser.parse_args();base=args.destination.resolve();base.mkdir(parents=True,exist_ok=True)
    archive=base/f'tika-app-{TIKA_VERSION}.zip'
    print('Downloading and verifying Apache Tika '+TIKA_VERSION,flush=True)
    download(TIKA_URL,archive,'sha512',TIKA_SHA512);unpack(archive,base/'tika')
    manifest={'tika':{'version':TIKA_VERSION,'url':TIKA_URL,'sha512':TIKA_SHA512}}
    if args.with_java:
        if sys.platform!='win32':parser.error('--with-java is only for Windows; use the system JRE on Linux')
        print('Downloading and verifying portable Eclipse Temurin JRE 21.0.13+9',flush=True)
        archive=base/'temurin-jre-21.0.13+9-windows-x64.zip'
        download(JAVA_URL,archive,'sha256',JAVA_SHA256);unpack(archive,base/'java')
        binaries=list((base/'java').glob('*/bin/java.exe'))
        if len(binaries)!=1:raise ValueError('Expected one portable Java runtime')
        manifest['java']={'version':'21.0.13+9','url':JAVA_URL,'sha256':JAVA_SHA256,
                          'relative_binary':binaries[0].relative_to(base).as_posix()}
    (base/'legacy-parser-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Verified parser tools installed in '+str(base),flush=True)


if __name__=='__main__':main()
