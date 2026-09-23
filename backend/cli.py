"""Offline account/bootstrap CLI. Never prints credentials."""
import argparse
import getpass
import os
from .auth import hash_password
from .repository import repository_from_env, restore_state, state_payload

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['init','add-user','seed-demo','set-demo'])
    parser.add_argument('--email')
    parser.add_argument('--display-name',default='Administrator')
    parser.add_argument('--workspace-name',default='PharmaScope')
    parser.add_argument('--workspace-id')
    parser.add_argument('--role',choices=['reader','analyst','reviewer','admin'],default='admin')
    args=parser.parse_args()
    from .pharma_scope_app import DomainState, uid, now
    store=repository_from_env()
    if store is None: parser.error('PHARMA_DATABASE_URL is required')
    with store.transaction():
        state=DomainState()
        existing=store.load()
        if existing: restore_state(state,existing)
        if args.action=='seed-demo':
            if os.getenv('PHARMA_RUNTIME_MODE') not in ('replay','demo'): parser.error('seed-demo requires explicit replay mode')
            if existing: parser.error('Database is already initialized; seed-demo never overwrites data')
        elif args.action=='set-demo':
            if not existing: parser.error('Database is not initialized')
            if not args.workspace_id or args.workspace_id not in state.workspaces:
                parser.error('--workspace-id must identify an existing workspace')
            if not args.email: parser.error('--email is required')
            selected=next((u for u in state.users.values() if u.get('email','').lower()==args.email.strip().lower()),None)
            member=state.memberships.get((args.workspace_id,selected['id'])) if selected else None
            if not selected or not selected.get('is_active',True) or not member or not member.get('enabled',True):
                parser.error('Demo account must be an active member of the workspace')
            for workspace in state.workspaces.values():
                workspace['public_demo']=workspace['id']==args.workspace_id
            state.workspaces[args.workspace_id]['demo_user_id']=selected['id']
            for key,session in list(state.sessions.items()):
                if session.get('guest'): state.sessions.pop(key,None)
        else:
            if not args.email or '@' not in args.email: parser.error('--email is required')
            if any(u.get('email','').lower()==args.email.lower() for u in state.users.values()): parser.error('Account exists; no changes made')
            password=os.getenv('PHARMA_ADMIN_PASSWORD') or getpass.getpass('New password (12+ characters): ')
            encoded=hash_password(password)
            ws=args.workspace_id
            if args.action=='init':
                if existing: parser.error('Database already initialized; use add-user')
                ws=ws or uid()
                state.workspaces[ws]={'id':ws,'name':args.workspace_name,'timezone':'UTC','created_at':now()}
            elif ws not in state.workspaces: parser.error('--workspace-id must identify an existing workspace')
            user=uid()
            state.users[user]={'id':user,'email':args.email.lower(),'display_name':args.display_name,'password_hash':encoded,'is_active':True,'created_at':now()}
            state.memberships[(ws,user)]={'workspace_id':ws,'user_id':user,'role':args.role,'enabled':True,'created_at':now()}
        store.save(state_payload(state))
    print('Initialized:',len(state.workspaces),'workspace(s),',len(state.users),'account(s)')
    for ws in state.workspaces.values(): print('Workspace:',ws['id'],ws['name'])

if __name__=='__main__': main()
