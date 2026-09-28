class Tokens {
  final String access, refresh;
  Tokens(this.access, this.refresh);
  factory Tokens.from(Map data) {
    final access = data['accessToken'], refresh = data['refreshToken'];
    if (access is! String ||
        refresh is! String ||
        access.isEmpty ||
        refresh.isEmpty) {
      throw const FormatException('Сервер вернул неполную сессию.');
    }
    return Tokens(access, refresh);
  }
}
