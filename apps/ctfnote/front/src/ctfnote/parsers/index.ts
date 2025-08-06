import CTFDParser from './ctfd';
import RawParser from './raw';
import HTBParser from './htb';
import PicoParser from './pico';
import justCTFParser from './justctf';
import AngstromParser from './angstrom';
import CINIParser from './cini';
import HitconParser from './hitcon';

export type ParsedTask = {
  title: string;
  tags: string[];
  description?: string;
  keep?: boolean;
};

export type Parser = {
  name: string;
  hint: string;
  parse(s: string): ParsedTask[];
};

export default [
  RawParser,
  CTFDParser,
  HTBParser,
  PicoParser,
  justCTFParser,
  AngstromParser,
  CINIParser,
  HitconParser,
];
