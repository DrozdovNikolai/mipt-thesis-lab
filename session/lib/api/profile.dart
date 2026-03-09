class Profile {
  final String name;
  final bool canEdit;
  Profile(this.name,this.canEdit);
  factory Profile.from(Map data){
    final names=[data['firstName'],data['lastName']].whereType<String>().where((s)=>s.isNotEmpty).join(' ');
    final permissions={...?data['privileges'] as List?,for(final role in data['roles']??[]) for(final p in role['privileges']??[]) p['name']};
    return Profile(names.isEmpty?data['login'] as String:names, permissions.contains('training:write') || permissions.contains('*'));
  }
}
