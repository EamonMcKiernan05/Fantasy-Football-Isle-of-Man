/** Fantasy Football Isle of Man - Frontend Application */

// State
const state = {
    user: JSON.parse(localStorage.getItem('ff_iom_user') || 'null'),
    team: null,
    gameweek: null,
    leaderboard: [],
    leagues: [],
    transferPlayerOut: null,
};

// API helpers
async function api(endpoint, options = {}) {
    const url = endpoint.startsWith('http') ? endpoint : endpoint;
    const defaults = {
        headers: { 'Content-Type': 'application/json' },
    };

    const resp = await fetch(url, { ...defaults, ...options });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: 'Request failed' }));
        throw new Error(err.detail || `HTTP ${resp.status}`);
    }
    return resp.json();
}

// Navigation
function showPage(page) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));

    const target = document.getElementById(`page-${page}`);
    if (target) target.classList.add('active');

    const link = document.querySelector(`.nav-link[data-page="${page}"]`);
    if (link) link.classList.add('active');

    switch(page) {
        case 'home': loadHome(); break;
        case 'my-team': loadMyTeam(); break;
        case 'transfers': loadTransfers(); break;
        case 'players': loadPlayers(); break;
        case 'gameweeks': loadGameweeks(); break;
        case 'leaderboard': loadLeaderboard(); break;
        case 'leagues': loadLeagues(); break;
    }
}

document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();
        showPage(link.dataset.page);
    });
});

// Toast
function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

// Auth
async function handleRegister(e) {
    e.preventDefault();
    const username = document.getElementById('reg-username').value;
    const email = document.getElementById('reg-email').value;
    const password = document.getElementById('reg-password').value;
    const teamName = document.getElementById('reg-team-name').value;

    try {
        const user = await api('/api/users/register', {
            method: 'POST',
            body: JSON.stringify({ username, email, password }),
        });

        await api(`/api/users/${user.id}/team/create`, {
            method: 'POST',
            body: JSON.stringify({ team_name: teamName }),
        });

        state.user = user;
        localStorage.setItem('ff_iom_user', JSON.stringify(user));
        localStorage.setItem('ff_iom_pass', password);
        updateNav();
        showToast(`Welcome ${username}! Team "${teamName}" created.`);
        showPage('my-team');
    } catch (err) {
        showToast(err.message, 'error');
    }
}

async function handleLogin(e) {
    e.preventDefault();
    const username = document.getElementById('login-username').value;
    const password = document.getElementById('login-password').value;

    try {
        const user = await api('/api/users/login', {
            method: 'POST',
            body: new URLSearchParams({ username, password }),
        });

        state.user = user;
        localStorage.setItem('ff_iom_user', JSON.stringify(user));
        updateNav();
        showToast(`Welcome back ${username}!`);
        showPage('my-team');
    } catch (err) {
        showToast('Invalid credentials', 'error');
    }
}

function logout() {
    state.user = null;
    state.team = null;
    localStorage.removeItem('ff_iom_user');
    updateNav();
    showPage('home');
}

function updateNav() {
    const navUser = document.getElementById('nav-user');
    const navAuth = document.getElementById('nav-auth');

    if (state.user) {
        navUser.style.display = 'flex';
        navAuth.style.display = 'none';
        document.getElementById('nav-username').textContent = state.user.username;
    } else {
        navUser.style.display = 'none';
        navAuth.style.display = 'flex';
    }
}

// HOME
async function loadHome() {
    const banner = document.getElementById('gw-banner');
    if (!banner) return;

    try {
        const data = await api('/api/gameweeks/current');
        if (data.gameweek) {
            const gw = data.gameweek;
            const deadline = new Date(gw.deadline).toLocaleString();
            banner.innerHTML = `
                <div>
                    <h3>Gameweek ${gw.number}</h3>
                    <p>${gw.fixtures ? gw.fixtures.length : 0} fixtures</p>
                </div>
                <div class="gw-deadline">
                    Deadline: ${deadline}
                    ${gw.closed ? '<span class="status-closed" style="padding:0.3rem 0.75rem;border-radius:4px;">Closed</span>' : '<span class="status-active" style="padding:0.3rem 0.75rem;border-radius:4px;">Open</span>'}
                </div>
            `;
        } else {
            banner.innerHTML = '<p>No active gameweek. Sync fixtures to start.</p>';
        }
    } catch (err) {
        banner.innerHTML = '<p>Could not load gameweek data.</p>';
    }
}

// MY TEAM
async function loadMyTeam() {
    if (!state.user) {
        showToast('Please login first', 'error');
        showPage('login');
        return;
    }

    try {
        state.team = await api(`/api/users/${state.user.id}/team`);
        renderMyTeam();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function renderMyTeam() {
    const team = state.team;
    if (!team) return;

    document.getElementById('team-name').textContent = team.name;
    document.getElementById('team-points').textContent = team.total_points;
    document.getElementById('team-budget').textContent = team.budget_remaining.toFixed(1);
    document.getElementById('team-transfers').textContent = team.free_transfers;

    // Nav points
    document.getElementById('nav-points').textContent = `${team.total_points} pts`;

    // Render formation
    renderPitch(team.squad);
    renderBench(team.squad);
    renderChips(team.chip_status);
}

function renderPitch(squad) {
    const container = document.getElementById('pitch-players');
    if (!container) return;
    container.innerHTML = '';

    const formation = document.getElementById('formation-select').value;
    const positions = getFormationPositions(formation);

    const starters = squad.filter(p => p.is_starting);
    const bench = squad.filter(p => !p.is_starting);

    // Sort starters by position
    const gk = starters.filter(p => p.player.position === 'GK');
    const defs = starters.filter(p => p.player.position === 'DEF');
    const mids = starters.filter(p => p.player.position === 'MID');
    const fwds = starters.filter(p => p.player.position === 'FWD');

    const allStarters = [...gk, ...defs, ...mids, ...fwds];

    positions.forEach((pos, i) => {
        if (i >= allStarters.length) return;
        const sp = allStarters[i];
        if (!sp || !sp.player) return;

        const playerDiv = document.createElement('div');
        playerDiv.className = 'pitch-player';
        playerDiv.style.left = pos.x + '%';
        playerDiv.style.top = pos.y + '%';

        const circleClass = sp.is_captain ? 'captain' : (sp.is_vice_captain ? 'vice' : '');
        const badge = sp.is_captain ? 'C' : (sp.is_vice_captain ? 'VC' : '');

        const posColor = {
            'GK': 'var(--gk)',
            'DEF': 'var(--def)',
            'MID': 'var(--mid)',
            'FWD': 'var(--fwd)',
        }[sp.player.position] || 'var(--text-muted)';

        playerDiv.innerHTML = `
            <div class="player-circle ${circleClass}" style="background:${posColor}">
                ${badge || sp.player.position}
            </div>
            <div class="player-name">${sp.player.name}</div>
            <div class="player-pts">${sp.total_points || 0}</div>
        `;

        playerDiv.onclick = () => setCaptainFromPitch(sp);
        container.appendChild(playerDiv);
    });
}

function renderBench(squad) {
    const container = document.getElementById('bench-grid');
    if (!container) return;
    container.innerHTML = '';

    const bench = squad.filter(p => !p.is_starting);
    bench.forEach(sp => {
        if (!sp.player) return;
        const div = document.createElement('div');
        div.className = `bench-player ${sp.was_autosub ? 'autosub' : ''}`;
        div.innerHTML = `
            <span class="pos-badge pos-${sp.player.position}">${sp.player.position}</span>
            <span>${sp.player.name}</span>
            <span style="margin-left:auto;color:var(--green)">${sp.total_points || 0}</span>
            ${sp.was_autosub ? '<span style="color:var(--yellow);font-size:0.75rem">SUB</span>' : ''}
        `;
        container.appendChild(div);
    });
}

function renderChips(chipStatus) {
    const container = document.getElementById('chips-grid');
    if (!container) return;

    const chips = [
        { id: 'wildcard_1', name: 'Wildcard (1st Half)', desc: 'Unlimited transfers. GW 1-19.', used: chipStatus.wildcard_first_half_used, action: 'wildcard' },
        { id: 'wildcard_2', name: 'Wildcard (2nd Half)', desc: 'Unlimited transfers. GW 20+.', used: chipStatus.wildcard_second_half_used, action: 'wildcard' },
        { id: 'free_hit', name: 'Free Hit', desc: 'Temporary squad for 1 GW.', used: chipStatus.free_hit_used, action: 'free_hit' },
        { id: 'bench_boost', name: 'Bench Boost', desc: 'All 15 players score.', used: chipStatus.bench_boost_used, action: 'bench_boost' },
        { id: 'triple_captain', name: 'Triple Captain', desc: 'Captain gets 3x points.', used: chipStatus.triple_captain_used, action: 'triple_captain' },
    ];

    container.innerHTML = chips.map(chip => `
        <div class="chip-card ${chip.used ? 'used' : 'available'}">
            <h4>${chip.name}</h4>
            <p>${chip.desc}</p>
            ${chip.used ? '<span style="color:var(--red)">USED</span>' :
              `<button class="btn btn-sm btn-primary" onclick="activateChip('${chip.action}')">Activate</button>`}
        </div>
    `).join('');
}

async function activateChip(chip) {
    if (!state.user) return;
    try {
        if (chip === 'wildcard') {
            showToast('Use wildcard through the Transfers page', 'info');
            showPage('transfers');
            return;
        }
        await api(`/api/users/${state.user.id}/team/chip`, {
            method: 'POST',
            body: JSON.stringify({ chip }),
        });
        showToast(`${chip.replace('_', ' ').toUpperCase()} activated!`);
        loadMyTeam();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function getFormationPositions(formation) {
    const [def, mid, fwd] = formation.split('-').map(Number);
    const positions = [];

    // GK at bottom
    positions.push({ x: 50, y: 90 });

    // DEF line
    const defY = 70;
    for (let i = 0; i < def; i++) {
        positions.push({ x: 20 + (i * 60 / (def - 1 || 1)), y: defY });
    }

    // MID line
    const midY = 45;
    for (let i = 0; i < mid; i++) {
        positions.push({ x: 15 + (i * 70 / (mid - 1 || 1)), y: midY });
    }

    // FWD line
    const fwdY = 20;
    for (let i = 0; i < fwd; i++) {
        positions.push({ x: 25 + (i * 50 / (fwd - 1 || 1)), y: fwdY });
    }

    return positions;
}

function changeFormation() {
    renderPitch(state.team.squad);
}

async function setCaptainFromPitch(sp) {
    if (!state.user) return;
    try {
        const vc = state.team.squad.find(p => !p.is_captain);
        await api(`/api/users/${state.user.id}/team/captain`, {
            method: 'PUT',
            body: JSON.stringify({
                captain_id: sp.id,
                vice_captain_id: vc ? vc.id : null,
            }),
        });
        showToast(`${sp.player.name} is now captain`);
        loadMyTeam();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

// TRANSFERS
async function loadTransfers() {
    if (!state.user) {
        showPage('login');
        return;
    }

    try {
        const status = await api(`/api/transfers/status/${state.user.id}`);
        document.getElementById('transfer-free').textContent = status.free_transfers;
        document.getElementById('transfer-budget').textContent = status.budget_remaining.toFixed(1);
        document.getElementById('wildcard-status').textContent =
            status.wildcard_first_half_available || status.wildcard_second_half_available ? 'Available' : 'Used';
    } catch (err) {
        // Ignore status errors
    }

    searchTransferPlayers();
}

async function searchTransferPlayers() {
    if (!state.user) return;

    const query = document.getElementById('transfer-search-input')?.value || '';
    const position = document.getElementById('transfer-position-filter')?.value || '';

    try {
        const params = new URLSearchParams();
        if (query) params.set('search', query);
        if (position) params.set('position', position);

        const players = await api(`/api/players/?${params}`);
        renderTransferList(players);
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function renderTransferList(players) {
    const container = document.getElementById('transfer-results');
    if (!container) return;

    const squadPlayerIds = new Set(
        (state.team?.squad || []).map(sp => sp.player_id)
    );

    container.innerHTML = players.map(p => {
        const inSquad = squadPlayerIds.has(p.id);
        return `
            <div class="player-card ${inSquad ? 'in-squad' : ''}"
                 onclick="${inSquad ? `selectPlayerOut(${p.id})` : `executeTransfer(${p.id})`}">
                <span class="pos-badge pos-${p.position}">${p.position}</span>
                <div class="player-info">
                    <div class="player-name">${p.name}</div>
                    <div class="player-team">${p.team_id ? 'Team ' + p.team_id : ''}</div>
                </div>
                <div class="player-stats">
                    <span class="player-price">${p.price.toFixed(1)}m</span>
                    ${inSquad ? '<span style="color:var(--green)">OWNED</span>' : ''}
                </div>
            </div>
        `;
    }).join('');
}

function selectPlayerOut(playerId) {
    if (!state.team) return;
    const sp = state.team.squad.find(s => s.player_id === playerId);
    if (!sp) return;

    state.transferPlayerOut = sp;
    const selectedDiv = document.getElementById('transfer-selected');
    selectedDiv.style.display = 'flex';
    document.getElementById('selected-out').innerHTML = `
        <span class="pos-badge pos-${sp.player.position}">${sp.player.position}</span>
        <strong>${sp.player.name}</strong>
        <span>${sp.player.price.toFixed(1)}m</span>
    `;
}

async function executeTransfer(playerInId) {
    if (!state.user || !state.transferPlayerOut) {
        showToast('Select a player to swap out first', 'error');
        return;
    }

    try {
        await api(`/api/transfers/`, {
            method: 'POST',
            body: JSON.stringify({
                player_in_id: playerInId,
                player_out_id: state.transferPlayerOut.player_id,
                user_id: state.user.id,
            }),
        });

        showToast('Transfer complete!');
        state.transferPlayerOut = null;
        document.getElementById('transfer-selected').style.display = 'none';
        loadMyTeam();
        loadTransfers();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

// PLAYERS
async function loadPlayers() {
    const query = document.getElementById('player-search')?.value || '';
    const position = document.getElementById('player-position')?.value || '';
    const sortBy = document.getElementById('player-sort')?.value || 'goals';

    try {
        const params = new URLSearchParams();
        if (query) params.set('search', query);
        if (position) params.set('position', position);
        params.set('order_by', sortBy);

        const players = await api(`/api/players/?${params}`);
        renderPlayerList(players);
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function renderPlayerList(players) {
    const container = document.getElementById('players-container');
    if (!container) return;

    const squadPlayerIds = new Set(
        (state.team?.squad || []).map(sp => sp.player_id)
    );

    container.innerHTML = players.map(p => `
        <div class="player-card ${squadPlayerIds.has(p.id) ? 'in-squad' : ''}">
            <span class="pos-badge pos-${p.position}">${p.position}</span>
            <div class="player-info">
                <div class="player-name">${p.name}</div>
                <div class="player-team">Team ${p.team_id || '?'}</div>
            </div>
            <div class="player-stats">
                <span class="player-price">${p.price.toFixed(1)}m</span>
                <span class="player-goals">${p.goals || 0}G</span>
                <span class="player-pts">${p.total_points || 0}</span>
                ${p.form ? `<span class="player-form">(${p.form})</span>` : ''}
                ${squadPlayerIds.has(p.id) ? '<span style="color:var(--green);margin-left:0.5rem">&#10003;</span>' : ''}
            </div>
        </div>
    `).join('');
}

// GAMEWEEKS
async function loadGameweeks() {
    const container = document.getElementById('gameweeks-container');
    if (!container) return;
    container.innerHTML = '<div class="loading">Loading...</div>';

    try {
        const data = await api('/api/gameweeks/');

        if (!data.length) {
            container.innerHTML = '<p>No gameweeks yet. Click "Sync Fixtures" to fetch.</p>';
            return;
        }

        container.innerHTML = data.map(gw => `
            <div class="gameweek-card">
                <div class="gameweek-header">
                    <div>
                        <strong>Gameweek ${gw.number}</strong>
                        <span style="color:var(--text-muted);margin-left:0.5rem;">${gw.season}</span>
                    </div>
                    <span class="gameweek-status ${gw.closed ? 'status-closed' : 'status-active'}">
                        ${gw.closed ? 'Closed' : 'Active'}
                    </span>
                </div>
                <p style="color:var(--text-muted);font-size:0.85rem;">
                    Deadline: ${new Date(gw.deadline).toLocaleString()}
                    | ${gw.fixture_count} fixtures
                    ${gw.scored ? '<span style="color:var(--green)"> | Scored</span>' : ''}
                </p>
            </div>
        `).join('');
    } catch (err) {
        container.innerHTML = `<p style="color:var(--red)">Error: ${err.message}</p>`;
    }
}

async function syncGameweeks() {
    try {
        const result = await api('/api/gameweeks/sync', { method: 'POST' });
        showToast(`Synced ${result.fixtures_synced || 0} fixtures`);
        loadGameweeks();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

// LEADERBOARD
async function loadLeaderboard() {
    const container = document.getElementById('leaderboard-container');
    if (!container) return;
    container.innerHTML = '<div class="loading">Loading...</div>';

    try {
        const data = await api('/api/leaderboard/');

        if (!data.entries.length) {
            container.innerHTML = '<p>No teams yet. Be the first to register!</p>';
            return;
        }

        let html = `
            <table class="table">
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>Manager</th>
                        <th>Team</th>
                        <th>Total</th>
                        <th>GW</th>
                    </tr>
                </thead>
                <tbody>
        `;

        data.entries.forEach(entry => {
            const rankClass = entry.rank <= 3 ? 'top3' : '';
            const isYou = state.user && entry.user_id === state.user.id;

            html += `
                <tr style="${isYou ? 'background:rgba(56,163,218,0.1)' : ''}">
                    <td class="leaderboard-rank ${rankClass}">${entry.rank}</td>
                    <td>${entry.username} ${isYou ? '(You)' : ''}</td>
                    <td>${entry.team_name}</td>
                    <td><strong class="pts-positive">${entry.total_points}</strong></td>
                    <td>${entry.gameweek_points != null ? entry.gameweek_points : '-'}</td>
                </tr>
            `;
        });

        html += '</tbody></table>';
        container.innerHTML = html;
    } catch (err) {
        container.innerHTML = `<p style="color:var(--red)">Error: ${err.message}</p>`;
    }
}

// LEAGUES
async function loadLeagues() {
    if (!state.user) {
        showPage('login');
        return;
    }

    const container = document.getElementById('leagues-container');
    if (!container) return;
    container.innerHTML = '<div class="loading">Loading...</div>';

    try {
        const data = await api(`/api/leagues/my-leagues/${state.user.id}`);

        if (!data.leagues.length) {
            container.innerHTML = '<p>No leagues yet. Create one or join with a code.</p>';
            return;
        }

        container.innerHTML = data.leagues.map(league => `
            <div class="league-card">
                <div class="card-header">
                    <div class="card-title">${league.name}</div>
                    <span class="league-code">${league.code}</span>
                </div>
                <p>Members: ${league.member_count} | Your rank: ${league.your_rank || '-'}</p>
                ${league.is_admin ? '<span style="color:var(--yellow)">Admin</span>' : ''}
            </div>
        `).join('');
    } catch (err) {
        container.innerHTML = `<p style="color:var(--red)">Error: ${err.message}</p>`;
    }
}

function showCreateLeague() {
    const name = prompt('League name:');
    if (!name) return;

    api('/api/leagues/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, is_h2h: false }),
        search: `user_id=${state.user.id}`,
    }).then(() => {
        showToast('League created!');
        loadLeagues();
    }).catch(err => showToast(err.message, 'error'));
}

function showJoinLeague() {
    const code = prompt('Enter league code:');
    if (!code) return;

    api(`/api/leagues/join?user_id=${state.user.id}`, {
        method: 'POST',
        body: JSON.stringify({ code }),
    }).then(() => {
        showToast('Joined league!');
        loadLeagues();
    }).catch(err => showToast(err.message, 'error'));
}

// Initialize
updateNav();
if (state.user) {
    // Load home data
    loadHome();
}
