document.getElementById('search')?.addEventListener('input', e => { const q=e.target.value.toLowerCase(); document.querySelectorAll('tr.item').forEach(r=>{r.hidden=!r.textContent.toLowerCase().includes(q);}); });

function openReview(){const id=location.hash.slice(1);const target=document.getElementById(id);if(target?.tagName==='DETAILS')target.open=true;}
window.addEventListener('hashchange',openReview);openReview();
